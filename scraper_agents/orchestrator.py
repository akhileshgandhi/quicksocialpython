"""
Orchestrator — FastAPI router + agent coordination.

Runs CrawlerAgent first, then parallel agents, then sequential agents,
then assembles SmartScrapeResponse.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Form, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

from models import (
    BrandIdentity,
    ContactInfo,
    ContentAsset,
    ProductFeature,
    ScrapedProduct,
    ScrapedService,
    SeoSocial,
    ServiceBenefit,
    ServiceSkill,
    SmartScrapeResponse,
    SocialLinks,
    TargetAudienceSegment,
    VisualBranding,
)
from utils import parse_product_features, parse_service_benefits, parse_service_skills

logger = logging.getLogger(__name__)

# ── In-memory store for async scrape jobs ─────────────────────────────────
_scrape_jobs: Dict[str, Dict[str, Any]] = {}

# ── In-memory queues for WebSocket progress streaming (not file-persisted) ─
_scrape_queues: Dict[str, asyncio.Queue] = {}

# File-based job store for multi-worker production deployments.
# In-memory dict is still used as a fast cache, but the file is the
# source of truth — all workers can read from it.
_JOBS_DIR: Optional[Path] = None  # set in create_agentic_scraper_router


def _save_job(scrape_id: str, data: Dict[str, Any]) -> None:
    """Persist job status to both memory and file."""
    _scrape_jobs[scrape_id] = data
    if _JOBS_DIR:
        try:
            job_file = _JOBS_DIR / f"_job_{scrape_id}.json"
            job_file.write_text(json.dumps(data, default=str), encoding="utf-8")
        except Exception:
            pass


def _load_job(scrape_id: str) -> Optional[Dict[str, Any]]:
    """Load job status from memory (fast) or file (cross-worker)."""
    if scrape_id in _scrape_jobs:
        return _scrape_jobs[scrape_id]
    if _JOBS_DIR:
        job_file = _JOBS_DIR / f"_job_{scrape_id}.json"
        if job_file.exists():
            try:
                data = json.loads(job_file.read_text(encoding="utf-8"))
                _scrape_jobs[scrape_id] = data  # cache in memory
                return data
            except Exception:
                pass
    return None


def _cleanup_old_jobs() -> None:
    """Remove completed/failed jobs older than 30 minutes."""
    cutoff = time.time() - 1800
    expired = [
        k for k, v in _scrape_jobs.items()
        if v.get("completed_at", v.get("started_at", 0)) < cutoff
    ]
    for k in expired:
        del _scrape_jobs[k]
    # Also clean old job files
    if _JOBS_DIR:
        for f in _JOBS_DIR.glob("_job_*.json"):
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
            except Exception:
                pass


def create_agentic_scraper_router(gemini_client, gemini_model: str, storage_dir: Path):
    """Factory — same signature as legacy create_scraper_router()."""
    global _JOBS_DIR
    _JOBS_DIR = storage_dir / "smart_scrape"
    _JOBS_DIR.mkdir(parents=True, exist_ok=True)

    router = APIRouter()

    @router.post("/smart-scrape-v2")
    async def smart_scrape_v2(
        request: Request,
        website_url: str = Form(...),
        company_name_hint: Optional[str] = Form(None),
        download_logo: bool = Form(True),
        deep_scrape: bool = Form(True),
    ):
        accept = request.headers.get("accept", "")
        if "text/event-stream" in accept:
            return StreamingResponse(
                _sse_wrapper(
                    website_url, company_name_hint, download_logo, deep_scrape,
                    gemini_client, gemini_model, storage_dir,
                ),
                media_type="text/event-stream",
            )
        result = await _run_agentic_scrape(
            website_url, company_name_hint, download_logo, deep_scrape,
            gemini_client, gemini_model, storage_dir,
        )
        return result

    @router.post("/smart-scrape-v2/async")
    async def smart_scrape_v2_async(
        website_url: str = Form(...),
        company_name_hint: Optional[str] = Form(None),
        download_logo: bool = Form(True),
        deep_scrape: bool = Form(True),
    ):
        """Fire-and-forget scrape — returns immediately with a scrape_id.

        Poll ``GET /smart-scrape-v2/status/{scrape_id}`` for results,
        or connect to ``WS /ws/smart-scrape/{scrape_id}`` for real-time progress.
        """
        _cleanup_old_jobs()
        scrape_id = uuid.uuid4().hex[:8]
        queue: asyncio.Queue = asyncio.Queue()
        _scrape_queues[scrape_id] = queue
        _save_job(scrape_id, {
            "status": "processing",
            "website_url": website_url,
            "started_at": time.time(),
        })

        async def _run_and_store():
            try:
                result = await _run_agentic_scrape(
                    website_url, company_name_hint, download_logo, deep_scrape,
                    gemini_client, gemini_model, storage_dir,
                    queue=queue,
                )
                _result_dict = result.model_dump()
                _save_job(scrape_id, {
                    "status": "done",
                    "result": _result_dict,
                    "completed_at": time.time(),
                })
                await queue.put({"step": "done", "message": "Completed", "result": _result_dict})
            except HTTPException as e:
                logger.error(f"[ASYNC SCRAPE] {scrape_id} failed: {e.detail}")
                _save_job(scrape_id, {
                    "status": "error",
                    "error": e.detail,
                    "completed_at": time.time(),
                })
                await queue.put({"step": "error", "message": "Brand scraping failed. Please try again.", "error": e.detail})
            except Exception as e:
                logger.error(f"[ASYNC SCRAPE] {scrape_id} failed: {e}")
                _save_job(scrape_id, {
                    "status": "error",
                    "error": str(e),
                    "completed_at": time.time(),
                })
                await queue.put({"step": "error", "message": "Brand scraping failed. Please try again.", "error": str(e)})
            finally:
                # Clean up queue after a delay to allow late WebSocket connects to drain it
                async def _drop_queue():
                    await asyncio.sleep(300)
                    _scrape_queues.pop(scrape_id, None)
                asyncio.create_task(_drop_queue())

        asyncio.create_task(_run_and_store())
        return {
            "scrape_id": scrape_id,
            "status": "processing",
            "message": f"Scraping started for '{website_url}'. Connect to /ws/smart-scrape/{scrape_id} for real-time progress.",
        }

    @router.get("/smart-scrape-v2/status/{scrape_id}")
    async def smart_scrape_v2_status(scrape_id: str):
        """Poll for async scrape results (works across multiple workers)."""
        job = _load_job(scrape_id)
        if not job:
            raise HTTPException(status_code=404, detail="Scrape job not found")
        return job

    # ═══════════════════════════════════════════════════════════════════════
    # WEBSOCKET — real-time scrape progress stream
    # ═══════════════════════════════════════════════════════════════════════
    @router.websocket("/ws/smart-scrape/{scrape_id}")
    async def ws_smart_scrape(websocket: WebSocket, scrape_id: str):
        """
        Stream brand scraping progress in real time.

        Start a job with POST /smart-scrape-v2/async, then connect here.

        Messages pushed by the server:
          {"step": "started",    "message": "Scanning website {url}..."}
          {"step": "crawling",   "message": "Mapping site structure..."}
          {"step": "analysing",  "message": "Analysing brand identity and content..."}
          {"step": "searching",  "message": "Filling data gaps with web search..."}
          {"step": "assembling", "message": "Assembling brand profile..."}
          {"step": "done",       "message": "Completed", "result": { full SmartScrapeResponse }}
          {"step": "error",      "message": "...", "error": "...details..."}
        """
        await websocket.accept()

        # Wait briefly for the job to be registered (race between HTTP response and WS connect)
        for _ in range(20):
            if scrape_id in _scrape_queues:
                break
            await asyncio.sleep(0.15)
        else:
            await websocket.send_json({"step": "error", "error": f"Invalid or expired scrape_id: {scrape_id}"})
            await websocket.close(code=1008)
            return

        q: asyncio.Queue = _scrape_queues[scrape_id]
        try:
            while True:
                message = await q.get()
                await websocket.send_json(message)
                if message.get("step") in ("done", "error"):
                    break
        except WebSocketDisconnect:
            logger.info(f"[WS] Client disconnected from scrape job {scrape_id}")
        finally:
            try:
                await websocket.close(code=1000)
            except Exception:
                pass

    return router


async def _sse_wrapper(
    website_url, company_name_hint, download_logo, deep_scrape,
    gemini_client, gemini_model, storage_dir,
):
    """SSE streaming wrapper — sends keepalive pings while scraping."""
    import asyncio

    task = asyncio.create_task(
        _run_agentic_scrape(
            website_url, company_name_hint, download_logo, deep_scrape,
            gemini_client, gemini_model, storage_dir,
        )
    )
    start = time.time()
    while not task.done():
        elapsed = int(time.time() - start)
        yield f"data: {json.dumps({'status': 'processing', 'elapsed': elapsed})}\n\n"
        await asyncio.sleep(10)

    try:
        result = task.result()
        yield f"data: {json.dumps({'status': 'done', 'result': result.model_dump()})}\n\n"
    except Exception as e:
        yield f"data: {json.dumps({'status': 'error', 'error': str(e)})}\n\n"


async def _run_agentic_scrape(
    website_url: str,
    company_name_hint: Optional[str],
    download_logo: bool,
    deep_scrape: bool,
    gemini_client,
    gemini_model: str,
    storage_dir: Path,
    queue: Optional[asyncio.Queue] = None,
) -> SmartScrapeResponse:
    """Main orchestration — Phase 1 → 2 → 3 → 4."""

    from scraper_agents.state import ScrapeState
    from scraper_agents.agents.crawler import CrawlerAgent
    from scraper_agents.agents.logo import LogoAgent
    from scraper_agents.agents.visual import VisualIdentityAgent
    from scraper_agents.agents.products import ProductAgent
    from scraper_agents.agents.content import ContentAssetsAgent
    from scraper_agents.agents.contact import ContactSocialAgent
    from scraper_agents.agents.brand_intelligence import BrandIntelligenceAgent
    from scraper_agents.agents.web_search import WebSearchAgent

    overall_start = time.time()
    scrape_id = uuid.uuid4().hex[:8]

    async def _push(msg: dict):
        if queue is not None:
            await queue.put(msg)

    # Initialize state
    state = ScrapeState(
        scrape_id=scrape_id,
        website_url=website_url,
        company_name_hint=company_name_hint,
        download_logo=download_logo,
        deep_scrape=deep_scrape,
        storage_dir=storage_dir,
        company_name=company_name_hint or "",
    )

    logger.info(f"\n{'='*60}")
    logger.info(f"[AGENTIC SCRAPE] {website_url} (id={scrape_id})")
    logger.info(f"{'='*60}")

    await _push({"step": "started", "message": f"Scanning website {website_url}..."})

    # ── Phase 1: Crawler (blocking) ──────────────────────────────────
    logger.info("\n[PHASE 1] CrawlerAgent — mapping site structure...")
    await _push({"step": "crawling", "message": "Mapping site structure..."})
    crawler = CrawlerAgent(gemini_client, gemini_model, storage_dir)
    await crawler.execute(state)

    if state.scrape_status == "failed":
        detail = state.fail_reason or "Could not fetch website content"
        raise HTTPException(status_code=502, detail=detail)

    phase1_time = time.time() - overall_start
    logger.info(f"[PHASE 1] complete in {phase1_time:.1f}s — "
                f"site_type={state.site_type}, pages_cached={len(state.page_cache)}")

    # ── Phase 2: Parallel agents ─────────────────────────────────────
    logger.info("\n[PHASE 2] Parallel agents — Logo, Visual, Products, Content, Contact...")
    await _push({"step": "analysing", "message": "Analysing brand identity and content..."})
    phase2_start = time.time()

    agents_2 = [
        LogoAgent(gemini_client, gemini_model, storage_dir),
        VisualIdentityAgent(gemini_client, gemini_model, storage_dir),
        ProductAgent(gemini_client, gemini_model, storage_dir),
        ContentAssetsAgent(gemini_client, gemini_model, storage_dir),
        ContactSocialAgent(gemini_client, gemini_model, storage_dir),
        BrandIntelligenceAgent(gemini_client, gemini_model, storage_dir),
    ]

    await asyncio.gather(*(agent.execute(state) for agent in agents_2))

    phase2_time = time.time() - phase2_start
    logger.info(f"[PHASE 2] complete in {phase2_time:.1f}s — "
                f"products={len(state.products)}, logo={'found' if state.logo_bytes else 'not found'}, "
                f"primary_color={state.primary_color}")

    # ── Phase 3: Web Search (fills gaps from Brand Intelligence) ─────
    logger.info("\n[PHASE 3] WebSearchAgent...")
    phase3_start = time.time()

    if state.data_gaps:
        await _push({"step": "searching", "message": "Filling data gaps with web search..."})
        ws_agent = WebSearchAgent(gemini_client, gemini_model, storage_dir)
        await ws_agent.execute(state)

    phase3_time = time.time() - phase3_start
    logger.info(f"[PHASE 3] complete in {phase3_time:.1f}s")

    # ── Phase 4: Assemble response ───────────────────────────────────
    logger.info("\n[PHASE 4] Assembling response...")
    await _push({"step": "assembling", "message": "Assembling brand profile..."})
    response = _assemble_response(state, overall_start)

    total_time = time.time() - overall_start
    logger.info(f"\n[AGENTIC SCRAPE] COMPLETE in {total_time:.1f}s "
                f"(P1={phase1_time:.1f}s, P2={phase2_time:.1f}s, P3={phase3_time:.1f}s)")

    # ── Save metadata to disk ─────────────────────────────────────
    _save_metadata(response, state, storage_dir)

    return response


def _assemble_response(state: ScrapeState, start_time: float) -> SmartScrapeResponse:
    """Build SmartScrapeResponse from ScrapeState."""

    bi = state.brand_identity

    def _str_field(val):
        """Coerce Gemini output to string — handles dict/list returns."""
        if val is None:
            return None
        if isinstance(val, str):
            return val
        if isinstance(val, dict):
            val = next(iter(val.values()), "") if val else ""
        if isinstance(val, list):
            val = val[0] if val else ""
        return str(val) if val else None

    brand_identity = BrandIdentity(
        name=_str_field(bi.get("name")) or state.company_name or state.domain,
        about=_str_field(bi.get("about")),
        country=_str_field(bi.get("country")),
        industry=_str_field(bi.get("industry")),
        tagline=_str_field(bi.get("tagline")),
        brand_voice=_str_field(bi.get("brand_voice")),
        brand_tone=_str_field(bi.get("brand_tone")),
        tone_attributes=bi.get("tone_attributes"),
        writing_style=_str_field(bi.get("writing_style")),
        brand_story=_str_field(bi.get("brand_story")),
        brand_values=bi.get("brand_values"),
        key_selling_points=bi.get("key_selling_points"),
        competitor_diff=_str_field(bi.get("competitor_diff")),
        target_audience=[
            TargetAudienceSegment(**seg) for seg in (bi.get("target_audience") or [])
            if isinstance(seg, dict) and seg.get("segment_name")
        ] or None,
        preferred_words=bi.get("preferred_words"),
        content_guidelines=bi.get("content_guidelines"),
        content_themes=bi.get("content_themes"),
    )

    visual_branding = VisualBranding(
        primary_color=state.primary_color,
        secondary_color=state.secondary_color,
        headline_font=state.headline_font,
        body_font=state.body_font,
        headline_text_color=state.headline_text_color,
        google_fonts_url=state.google_fonts_url,
        logo_url=state.logo_cloudinary_url or state.logo_url,
        logo_local_path=state.logo_local_path,
    )

    ss = state.seo_social
    seo_social = SeoSocial(
        keywords=ss.get("keywords"),
        hashtags=ss.get("hashtags"),
        things_to_avoid=ss.get("things_to_avoid"),
    )

    sl = state.social_links
    social_links = SocialLinks(
        facebook=sl.get("facebook"),
        instagram=sl.get("instagram"),
        twitter=sl.get("twitter"),
        linkedin=sl.get("linkedin"),
        youtube=sl.get("youtube"),
        tiktok=sl.get("tiktok"),
        pinterest=sl.get("pinterest"),
        github=sl.get("github"),
        other=sl.get("other"),
    ) if sl else None

    ci = state.contact_info
    contact_info = ContactInfo(
        emails=ci.get("emails"),
        phones=ci.get("phones"),
        addresses=ci.get("addresses"),
        contact_page_url=ci.get("contact_page_url"),
    ) if ci else None

    # Match image URLs for products that don't have them (e.g. from WebSearch)
    # This runs after all phases so it catches products from any source.
    if state.products and state.page_cache:
        from scraper_agents.agents.crawler import CrawlerAgent
        _crawler_dummy = CrawlerAgent.__new__(CrawlerAgent)
        _crawler_dummy.agent_name = "crawler"
        # Temporarily put final products into discovered_products for matching
        _orig = state.discovered_products
        state.discovered_products = state.products
        _crawler_dummy._match_product_image_urls(state)
        state.products = state.discovered_products
        state.discovered_products = _orig

    # Build products
    products = []
    for p in state.products:
        if isinstance(p, dict):
            products.append(ScrapedProduct(
                name=p.get("name", "Unknown"),
                description=p.get("description"),
                category=p.get("category"),
                price=p.get("price"),
                url=p.get("url") or p.get("source_url"),
                tags=p.get("tags"),
                features=parse_product_features(p.get("features")) if p.get("features") else None,
                image_urls=p.get("image_urls"),
            ))

    # Build services
    services = []
    for s in state.services:
        if isinstance(s, dict):
            services.append(ScrapedService(
                name=s.get("name", "Unknown"),
                description=s.get("description"),
                category=s.get("category"),
                pricing=s.get("pricing"),
                url=s.get("url") or s.get("source_url"),
                duration=s.get("duration"),
                tags=s.get("tags"),
                benefits=parse_service_benefits(s.get("benefits")) if s.get("benefits") else None,
                skills=parse_service_skills(s.get("skills")) if s.get("skills") else None,
                image_urls=s.get("image_urls"),
                video_urls=s.get("video_urls"),
            ))

    # Build content assets
    content_assets = [
        ContentAsset(
            title=a.get("title", "Untitled"),
            asset_type=a.get("asset_type", "other"),
            url=a.get("url"),
            download_url=a.get("download_url"),
            thumbnail_url=a.get("thumbnail_url"),
            description=a.get("description"),
            file_type=a.get("file_type"),
        )
        for a in state.content_assets if isinstance(a, dict) and a.get("title")
    ] or None

    total_time = time.time() - start_time

    return SmartScrapeResponse(
        scrape_id=state.scrape_id,
        website_url=state.website_url,
        scrape_status=state.scrape_status,
        data_source=state.data_source,
        brand_identity=brand_identity,
        visual_branding=visual_branding,
        seo_social=seo_social,
        social_links=social_links,
        contact_info=contact_info,
        products=products,
        services=services,
        content_assets=content_assets,
        scraped_at=datetime.utcnow().isoformat(),
        scrape_summary={
            "scrape_id": state.scrape_id,
            "site_type": state.site_type,
            "pages_cached": len(state.page_cache),
            "sitemap_products": len(state.sitemap_urls),
            "products_found": len(products),
            "services_found": len(services),
            "content_assets_found": len(content_assets or []),
            "logo_found": state.logo_local_path is not None,
            "colors_extracted": bool(state.primary_color),
            "visual_analysis": bool(state.visual_analysis),
            "data_gaps": state.data_gaps,
            "total_time_seconds": round(total_time, 1),
            "engine": "agentic_v2",
            "llm_usage": {
                "total_calls": len(state.llm_calls),
                "total_prompt_tokens": sum(c.get("prompt_tokens", 0) for c in state.llm_calls),
                "total_output_tokens": sum(c.get("output_tokens", 0) for c in state.llm_calls),
                "total_tokens": sum(c.get("total_tokens", 0) for c in state.llm_calls),
                "calls": state.llm_calls,
            },
        },
    )


def _save_metadata(response: SmartScrapeResponse, state, storage_dir: Path) -> None:
    """Save scrape_metadata.json to disk (matches old scraper.py behavior)."""
    try:
        name = response.brand_identity.name if response.brand_identity else state.domain
        sanitized = re.sub(r'[^\w\s-]', '', (name or "unknown").lower())
        sanitized = re.sub(r'[-\s]+', '_', sanitized)[:30]

        output_folder = storage_dir / "smart_scrape" / f"{state.scrape_id}_{sanitized}"
        output_folder.mkdir(parents=True, exist_ok=True)

        metadata_file = output_folder / "scrape_metadata.json"
        with open(metadata_file, 'w', encoding='utf-8') as f:
            json.dump(response.model_dump(), f, indent=2, ensure_ascii=False)

        logger.info(f"[METADATA] saved to {metadata_file}")
    except Exception as e:
        logger.warning(f"[METADATA] failed to save: {e}")

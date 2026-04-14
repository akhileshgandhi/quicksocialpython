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
from typing import Any, Dict, List, Optional, Sequence
from urllib.parse import urlparse

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

from scraper_agents.state import ScrapeState

logger = logging.getLogger(__name__)

# ── In-memory store for async scrape jobs ─────────────────────────────────
_scrape_jobs: Dict[str, Dict[str, Any]] = {}
# Live progress queues for WebSocket streaming (async scrapes only)
_scrape_queues: Dict[str, asyncio.Queue] = {}
_QUEUE_CLEANUP_DELAY_S = 120.0

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


async def _schedule_scrape_queue_cleanup(scrape_id: str, delay_s: float = _QUEUE_CLEANUP_DELAY_S) -> None:
    """Remove queue after delay so late WebSocket clients can still resolve scrape_id."""
    await asyncio.sleep(delay_s)
    _scrape_queues.pop(scrape_id, None)


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


def create_agentic_scraper_router(gemini_client, text_models: Sequence[str], storage_dir: Path):
    """Factory — *text_models* is an ordered fallback list (same as main app)."""
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
                    gemini_client, text_models, storage_dir,
                ),
                media_type="text/event-stream",
            )
        result = await _run_agentic_scrape(
            website_url, company_name_hint, download_logo, deep_scrape,
            gemini_client, text_models, storage_dir,
        )
        return result

    @router.post("/smart-scrape-v2/async")
    async def smart_scrape_v2_async(
        website_url: str = Form(...),
        company_name_hint: Optional[str] = Form(None),
        download_logo: bool = Form(True),
        deep_scrape: bool = Form(True),
    ):
        """Fire-and-forget scrape — returns immediately with scrape_id and message.

        First response body::

            {"scrape_id": "...", "status": "processing",
             "message": "Scraping started for '<url>'. Connect to /ws/smart-scrape/<id> for real-time progress."}

        Poll ``GET /smart-scrape-v2/status/{scrape_id}`` for results, or connect to
        ``/ws/smart-scrape/{scrape_id}`` for real-time progress events.
        """
        _cleanup_old_jobs()
        website_url = (website_url or "").strip()
        scrape_id = uuid.uuid4().hex[:8]
        progress_q: asyncio.Queue = asyncio.Queue()
        _scrape_queues[scrape_id] = progress_q

        _save_job(scrape_id, {
            "status": "processing",
            "website_url": website_url,
            "started_at": time.time(),
        })

        await progress_q.put({
            "step": "started",
            "message": f"Scanning website {website_url}...",
            "scrape_id": scrape_id,
        })

        async def _run_and_store():
            try:
                result = await _run_agentic_scrape(
                    website_url, company_name_hint, download_logo, deep_scrape,
                    gemini_client, text_models, storage_dir,
                    progress_queue=progress_q,
                    preset_scrape_id=scrape_id,
                )
                try:
                    result_payload = result.model_dump(mode="json")
                except TypeError:
                    result_payload = result.model_dump()
                _save_job(scrape_id, {
                    "status": "done",
                    "result": result_payload,
                    "completed_at": time.time(),
                })
                await progress_q.put({
                    "step": "done",
                    "message": "Completed",
                    "result": result_payload,
                    "scrape_id": scrape_id,
                })
            except HTTPException as e:
                err = e.detail if isinstance(e.detail, str) else str(e.detail)
                logger.error(f"[ASYNC SCRAPE] {scrape_id} failed: {e}")
                _save_job(scrape_id, {
                    "status": "error",
                    "error": err,
                    "completed_at": time.time(),
                })
                await progress_q.put({
                    "step": "error",
                    "message": "Scrape failed",
                    "error": err,
                    "scrape_id": scrape_id,
                })
            except Exception as e:
                logger.error(f"[ASYNC SCRAPE] {scrape_id} failed: {e}")
                _save_job(scrape_id, {
                    "status": "error",
                    "error": str(e),
                    "completed_at": time.time(),
                })
                await progress_q.put({
                    "step": "error",
                    "message": "Scrape failed",
                    "error": str(e),
                    "scrape_id": scrape_id,
                })
            finally:
                asyncio.create_task(_schedule_scrape_queue_cleanup(scrape_id))

        asyncio.create_task(_run_and_store())
        message = (
            f"Scraping started for '{website_url}'. "
            f"Connect to /ws/smart-scrape/{scrape_id} for real-time progress."
        )
        return {
            "scrape_id": scrape_id,
            "status": "processing",
            "message": message,
        }

    @router.websocket("/ws/smart-scrape/{scrape_id}")
    async def ws_smart_scrape(websocket: WebSocket, scrape_id: str):
        """Stream JSON progress events for an async scrape (same ``scrape_id`` from POST)."""
        await websocket.accept()
        deadline = time.time() + 60.0
        while scrape_id not in _scrape_queues and time.time() < deadline:
            await asyncio.sleep(0.05)
        q = _scrape_queues.get(scrape_id)
        if q is None:
            try:
                await websocket.send_json({
                    "step": "error",
                    "message": "Unknown or expired scrape job",
                    "error": "unknown or expired scrape_id (connect within 60s of starting async scrape)",
                    "scrape_id": scrape_id,
                })
            except Exception:
                pass
            try:
                await websocket.close(code=4404)
            except Exception:
                # Client might already have closed; avoid send-after-close runtime errors.
                pass
            return
        try:
            while True:
                try:
                    message = await asyncio.wait_for(q.get(), timeout=3600.0)
                except asyncio.TimeoutError:
                    break
                await websocket.send_json(message)
                if isinstance(message, dict) and message.get("step") in ("done", "error"):
                    break
        except WebSocketDisconnect:
            pass
        finally:
            try:
                await websocket.close()
            except Exception:
                pass

    @router.get("/smart-scrape-v2/status/{scrape_id}")
    async def smart_scrape_v2_status(scrape_id: str):
        """Poll for async scrape results (works across multiple workers)."""
        job = _load_job(scrape_id)
        if not job:
            raise HTTPException(status_code=404, detail="Scrape job not found")
        return job

    return router


async def _sse_wrapper(
    website_url, company_name_hint, download_logo, deep_scrape,
    gemini_client, text_models, storage_dir,
):
    """SSE streaming wrapper — sends keepalive pings while scraping."""
    import asyncio

    task = asyncio.create_task(
        _run_agentic_scrape(
            website_url, company_name_hint, download_logo, deep_scrape,
            gemini_client, text_models, storage_dir,
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
    text_models: Sequence[str],
    storage_dir: Path,
    progress_queue: Optional[asyncio.Queue] = None,
    preset_scrape_id: Optional[str] = None,
) -> SmartScrapeResponse:
    """Main orchestration — Phase 1 → 2 → 3 → 4.

    When *progress_queue* is set (async + WebSocket), each event is JSON with
    ``step``, ``message``, ``scrape_id``; the final ``done`` event also includes
    ``result`` (full :class:`~models.SmartScrapeResponse` payload, JSON-safe).
    *preset_scrape_id* keeps ``scrape_id`` aligned with ``POST /smart-scrape-v2/async``.
    """

    from scraper_agents.agents.crawler import CrawlerAgent
    from scraper_agents.agents.logo import LogoAgent
    from scraper_agents.agents.visual import VisualIdentityAgent
    from scraper_agents.agents.products import ProductAgent
    from scraper_agents.agents.content import ContentAssetsAgent
    from scraper_agents.agents.contact import ContactSocialAgent
    from scraper_agents.agents.brand_intelligence import BrandIntelligenceAgent
    from scraper_agents.agents.web_search import WebSearchAgent

    overall_start = time.time()
    scrape_id = preset_scrape_id or uuid.uuid4().hex[:8]

    async def _progress(step: str, message: str, **extra: Any) -> None:
        if progress_queue:
            try:
                payload: Dict[str, Any] = {
                    "step": step,
                    "message": message,
                    "scrape_id": scrape_id,
                    **extra,
                }
                await progress_queue.put(payload)
            except Exception:
                pass

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

    # ── Phase 1: Crawler (blocking) ──────────────────────────────────
    await _progress("crawling", "Mapping site structure...")
    logger.info("\n[PHASE 1] CrawlerAgent — mapping site structure...")
    _primary = text_models[0] if text_models else ""
    crawler = CrawlerAgent(
        gemini_client, _primary, storage_dir, text_models=text_models,
    )
    await crawler.execute(state)

    if state.scrape_status == "failed":
        raise HTTPException(status_code=502, detail="Could not fetch website content")

    phase1_time = time.time() - overall_start
    logger.info(f"[PHASE 1] complete in {phase1_time:.1f}s — "
                f"site_type={state.site_type}, pages_cached={len(state.page_cache)}")

    # ── Phase 2: Parallel agents ─────────────────────────────────────
    await _progress("analysing", "Analysing brand identity and content...")
    logger.info("\n[PHASE 2] Parallel agents — Logo, Visual, Products, Content, Contact...")
    phase2_start = time.time()

    agents_2 = [
        LogoAgent(gemini_client, _primary, storage_dir, text_models=text_models),
        VisualIdentityAgent(gemini_client, _primary, storage_dir, text_models=text_models),
        ProductAgent(gemini_client, _primary, storage_dir, text_models=text_models),
        ContentAssetsAgent(gemini_client, _primary, storage_dir, text_models=text_models),
        ContactSocialAgent(gemini_client, _primary, storage_dir, text_models=text_models),
        BrandIntelligenceAgent(gemini_client, _primary, storage_dir, text_models=text_models),
    ]

    await asyncio.gather(*(agent.execute(state) for agent in agents_2))

    phase2_time = time.time() - phase2_start
    logger.info(f"[PHASE 2] complete in {phase2_time:.1f}s — "
                f"products={len(state.products)}, logo={'found' if state.logo_bytes else 'not found'}, "
                f"palette={state.brand_palette}")

    # ── Phase 3: Web Search (fills gaps from Brand Intelligence) ─────
    if state.data_gaps:
        search_msg = "Filling data gaps with web search..."
    else:
        search_msg = "No additional web search needed."
    await _progress("searching", search_msg, skipped=not bool(state.data_gaps))
    logger.info("\n[PHASE 3] WebSearchAgent...")
    phase3_start = time.time()

    if state.data_gaps:
        ws_agent = WebSearchAgent(gemini_client, _primary, storage_dir, text_models=text_models)
        await ws_agent.execute(state)

    phase3_time = time.time() - phase3_start
    logger.info(f"[PHASE 3] complete in {phase3_time:.1f}s")

    # ── Phase 4: Assemble response ───────────────────────────────────
    await _progress("assembling", "Assembling brand profile...")
    logger.info("\n[PHASE 4] Assembling response...")
    response = _assemble_response(state, overall_start)

    total_time = time.time() - overall_start
    logger.info(f"\n[AGENTIC SCRAPE] COMPLETE in {total_time:.1f}s "
                f"(P1={phase1_time:.1f}s, P2={phase2_time:.1f}s, P3={phase3_time:.1f}s)")

    # ── Save metadata to disk ─────────────────────────────────────
    _save_metadata(response, state, storage_dir)
    _append_domain_brand_index(storage_dir, state)

    return response


def _append_domain_brand_index(storage_dir: Path, state) -> None:
    """Persist latest brand palette per registrable domain for quick lookup across scrapes."""
    try:
        url = (state.website_url or "").strip()
        if not url or not state.brand_palette:
            return
        domain = urlparse(url).netloc.lower()
        if domain.startswith("www."):
            domain = domain[4:]
        if not domain:
            return
        path = storage_dir / "smart_scrape" / "_domain_brand_colors.json"
        data: Dict[str, Any] = {}
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
        ca = state.color_audit or {}
        data[domain] = {
            "last_scrape_id": state.scrape_id,
            "last_updated": datetime.utcnow().isoformat() + "Z",
            "website_url": state.website_url,
            "brand_palette": dict(state.brand_palette),
            "color_audit_summary": {
                "primary_source": ca.get("primary_source"),
                "rules_fired": ca.get("rules_fired"),
                "pipeline_version": ca.get("pipeline_version"),
            },
        }
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        logger.debug("[domain_brand_index] failed: %s", e)


def _parse_rgb(hex_color: str) -> tuple[int, int, int]:
    """Return (R, G, B) ints from a 3- or 6-digit hex string."""
    h = (hex_color or "").lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) < 6:
        h = h.ljust(6, "0")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _normalize_hex_color_list(colors: Optional[List[str]], max_colors: int = 24) -> List[str]:
    """Dedupe, normalize to ``#RRGGBB`` uppercase, preserve order."""
    seen: set = set()
    out: List[str] = []
    for c in colors or []:
        if not c or not isinstance(c, str):
            continue
        h = c.strip().upper()
        if not h.startswith("#"):
            h = "#" + h
        if len(h) == 4 and h.startswith("#"):
            h = "#" + "".join(ch * 2 for ch in h[1:])
        if len(h) >= 7:
            h = h[:7]
            if h not in seen:
                seen.add(h)
                out.append(h)
        if len(out) >= max_colors:
            break
    return out


def _normalize_hex_one(raw: Optional[str]) -> Optional[str]:
    """Normalize a single hex string to ``#RRGGBB`` or ``None`` if invalid."""
    out = _normalize_hex_color_list([raw] if raw else [], max_colors=1)
    return out[0] if out else None


def _visual_branding_hex_triple(state: ScrapeState) -> tuple[str, str, str]:
    """Primary / secondary / accent for ``VisualBranding`` from ``brand_palette``.

    Per-slot fallbacks when a key is missing: ``#1A1A2E``, ``#FFFFFF``, ``#4F46E5``.
    Rollback (list or merged swatches): ``VISUAL_BRANDING_ROLLBACK.md``.
    """
    bp = state.brand_palette or {}
    d1, d2, d3 = "#1A1A2E", "#FFFFFF", "#4F46E5"
    p = _normalize_hex_one(bp.get("primary") if isinstance(bp.get("primary"), str) else None)
    s = _normalize_hex_one(bp.get("secondary") if isinstance(bp.get("secondary"), str) else None)
    a = _normalize_hex_one(bp.get("accent") if isinstance(bp.get("accent"), str) else None)
    return (p or d1, s or d2, a or d3)


def _contrast_ratio(hex1: str, hex2: str) -> float:
    """WCAG relative luminance contrast ratio between two hex colours."""
    def _rel_lum(hex_c: str) -> float:
        r, g, b = _parse_rgb(hex_c)
        rs, gs, bs = r / 255.0, g / 255.0, b / 255.0
        rs = rs / 12.92 if rs <= 0.03928 else ((rs + 0.055) / 1.055) ** 2.4
        gs = gs / 12.92 if gs <= 0.03928 else ((gs + 0.055) / 1.055) ** 2.4
        bs = bs / 12.92 if bs <= 0.03928 else ((bs + 0.055) / 1.055) ** 2.4
        return 0.2126 * rs + 0.7152 * gs + 0.0722 * bs

    l1 = _rel_lum(hex1) + 0.05
    l2 = _rel_lum(hex2) + 0.05
    return max(l1, l2) / min(l1, l2)


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

    primary_hex, secondary_hex, accent_hex = _visual_branding_hex_triple(state)

    headline_text_color = state.headline_text_color
    if not headline_text_color or _contrast_ratio(primary_hex, headline_text_color) < 4.5:
        headline_text_color = "#FFFFFF"

    visual_branding = VisualBranding(
        primary_color=primary_hex,
        secondary_color=secondary_hex,
        accent_color=accent_hex,
        headline_font=state.headline_font,
        body_font=state.body_font,
        headline_text_color=headline_text_color,
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
            "colors_extracted": bool(state.primary_color or state.colors_found or state.brand_palette),
            "visual_analysis": bool(state.visual_analysis),
            "data_gaps": state.data_gaps,
            "total_time_seconds": round(total_time, 1),
            "engine": "agentic_v2",
        },
        color_audit=state.color_audit,
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

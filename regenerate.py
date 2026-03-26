from fastapi import APIRouter, HTTPException, Form, UploadFile, File
from google.genai import types
from PIL import Image
from io import BytesIO
from typing import Optional
from pathlib import Path
from datetime import datetime
import base64
import os
import re
import json
import uuid
import logging

from models import RegenerateImageResponse
from utils import download_reference_image

logger = logging.getLogger(__name__)

_SWAGGER_PLACEHOLDERS = {"string", "null", "undefined", "none", ""}


def _clean_optional(value: Optional[str]) -> Optional[str]:
    """Return None if value is empty or a Swagger UI default placeholder."""
    if value is None:
        return None
    stripped = value.strip()
    if stripped.lower() in _SWAGGER_PLACEHOLDERS:
        return None
    return stripped


def _upload_to_cloudinary(image_bytes: bytes, folder: str, public_id: str) -> Optional[str]:
    """Upload image to Cloudinary CDN. Returns secure_url or None."""
    try:
        import cloudinary
        import cloudinary.uploader

        cloud_name = os.environ.get("CLOUDINARY_CLOUD_NAME")
        api_key = os.environ.get("CLOUDINARY_API_KEY")
        api_secret = os.environ.get("CLOUDINARY_API_SECRET")
        if not all([cloud_name, api_key, api_secret]):
            logger.warning("[CLOUDINARY] Missing credentials, skipping upload")
            return None

        cloudinary.config(
            cloud_name=cloud_name,
            api_key=api_key,
            api_secret=api_secret,
            secure=True,
        )
        result = cloudinary.uploader.upload(
            BytesIO(image_bytes),
            folder=folder,
            public_id=public_id,
            overwrite=True,
            resource_type="image",
        )
        url = result.get("secure_url")
        logger.info(f"[CLOUDINARY] Uploaded: {url}")
        return url
    except ImportError:
        logger.warning("[CLOUDINARY] cloudinary package not installed")
        return None
    except Exception as e:
        logger.warning(f"[CLOUDINARY] Upload failed: {e}")
        return None



def create_regenerate_router(gemini_client, gemini_model, image_model, storage_dir):
    router = APIRouter(tags=["Regenerate"])

    async def _resolve_source_image(
        image_file: Optional[UploadFile],
        image_url: Optional[str],
        image_path: Optional[str],
    ):
        """
        Load image bytes from one of three sources (priority: file > url > path).
        Returns (image_bytes, mime_type, source_label, original_metadata_or_None).
        """
        image_bytes = None
        mime_type = "image/png"
        source_label = None
        original_metadata = None

        # --- Priority 1: Direct file upload ---
        if image_file is not None:
            image_bytes = await image_file.read()
            source_label = image_file.filename or "upload"
            if image_bytes[:3] == b'\xff\xd8\xff':
                mime_type = "image/jpeg"
            elif image_bytes[:4] == b'\x89PNG':
                mime_type = "image/png"
            elif image_bytes[:4] == b'RIFF':
                mime_type = "image/webp"

        # --- Priority 2: URL (external or local /images/... path) ---
        elif image_url and image_url.strip():
            url = image_url.strip()

            # Local reference: /images/marketing_posts/abc/post.png
            if url.startswith("/images/"):
                rel = url[len("/images/"):]
                file_path = (storage_dir / rel).resolve()
                # Security: ensure path is within storage_dir
                if not str(file_path).startswith(str(storage_dir.resolve())):
                    raise HTTPException(status_code=400, detail="Invalid image URL path")
                if not file_path.exists():
                    raise HTTPException(status_code=400, detail=f"Image not found: {url}")
                image_bytes = file_path.read_bytes()
                source_label = url
                # Check for .json sidecar
                sidecar = file_path.with_suffix(".json")
                if sidecar.exists():
                    try:
                        original_metadata = json.loads(sidecar.read_text(encoding="utf-8"))
                    except Exception:
                        pass
                if file_path.suffix.lower() in (".jpg", ".jpeg"):
                    mime_type = "image/jpeg"
            else:
                # External URL
                result = download_reference_image(url)
                if not result or not result.get("success"):
                    raise HTTPException(status_code=400, detail=f"Failed to download image from URL: {url}")
                image_bytes = result["image_bytes"]
                mime_type = result.get("mime_type", "image/png")
                source_label = url

        # --- Priority 3: Relative path within generated_images/ ---
        elif image_path and image_path.strip():
            rel = image_path.strip().lstrip("/\\")
            file_path = (storage_dir / rel).resolve()
            # Security: prevent directory traversal
            if not str(file_path).startswith(str(storage_dir.resolve())):
                raise HTTPException(status_code=400, detail="Invalid image path (directory traversal blocked)")
            if not file_path.exists():
                raise HTTPException(status_code=400, detail=f"Image not found at path: {image_path}")
            image_bytes = file_path.read_bytes()
            source_label = image_path
            # Check for .json sidecar
            sidecar = file_path.with_suffix(".json")
            if sidecar.exists():
                try:
                    original_metadata = json.loads(sidecar.read_text(encoding="utf-8"))
                except Exception:
                    pass
            if file_path.suffix.lower() in (".jpg", ".jpeg"):
                mime_type = "image/jpeg"

        else:
            raise HTTPException(
                status_code=400,
                detail="No image provided. Supply one of: image_file, image_url, or image_path",
            )

        # Validate image opens with PIL
        try:
            img = Image.open(BytesIO(image_bytes))
            img.verify()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid or corrupt image file")

        # File size check (20 MB)
        if len(image_bytes) > 20 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Image exceeds 20 MB limit")

        return image_bytes, mime_type, source_label, original_metadata

    # =========================================================================
    # ENDPOINT
    # =========================================================================

    @router.post("/regenerate-image", response_model=RegenerateImageResponse)
    async def regenerate_image(
        # Image source (at least one required)
        image_file: Optional[UploadFile] = File(None, description="Upload the image to edit"),
        image_url: Optional[str] = Form(None, description="URL of the image (including /images/... local paths)"),
        image_path: Optional[str] = Form(None, description="Relative path in generated_images/ (e.g. marketing_posts/abc/post.png)"),

        # Edit instruction (required)
        modification_prompt: str = Form(..., description="What to change (e.g. 'change background to blue')"),

        # Optional
        logo_file: Optional[UploadFile] = File(None, description="Logo to integrate into the edited image"),
        logo_url: Optional[str] = Form(None, description="Logo URL to integrate"),
        temperature: Optional[float] = Form(0.75, description="Creativity 0.0-1.0. Lower = closer to original."),
        generate_caption: Optional[bool] = Form(False, description="Generate a new caption for the edited image"),
        company_name: Optional[str] = Form(None, description="Company name (for caption context)"),
        company_profile: Optional[str] = Form(None, description="Company description (for caption context)"),
    ):
        try:
            # Sanitize optional strings (Swagger sends "string" as default)
            image_url = _clean_optional(image_url)
            image_path = _clean_optional(image_path)
            logo_url = _clean_optional(logo_url)
            company_name = _clean_optional(company_name)
            company_profile = _clean_optional(company_profile)

            logger.info("\n" + "=" * 70)
            logger.info("[REGENERATE] Processing image edit request")
            logger.info("=" * 70)

            # =================================================================
            # STEP 1: Resolve source image
            # =================================================================
            logger.info("[STEP 1] Resolving source image...")
            source_bytes, source_mime, source_label, original_metadata = await _resolve_source_image(
                image_file, image_url, image_path,
            )

            # Get dimensions
            img_pil = Image.open(BytesIO(source_bytes))
            width, height = img_pil.size
            logger.info(f"   Source: {source_label} ({width}x{height}, {len(source_bytes)} bytes)")

            # =================================================================
            # STEP 2: Handle optional logo
            # =================================================================
            logo_bytes = None
            if logo_file is not None:
                logo_bytes = await logo_file.read()
                logger.info(f"[STEP 3] Logo uploaded: {len(logo_bytes)} bytes")
            elif logo_url and logo_url.strip():
                try:
                    import requests as _req
                    _r = _req.get(logo_url.strip(), timeout=15, headers={"User-Agent": "QuickSocial/1.0"})
                    if _r.status_code == 200 and _r.content:
                        logo_bytes = _r.content
                        logger.info(f"[STEP 3] Logo fetched from URL: {logo_url} ({len(logo_bytes)} bytes)")
                    else:
                        logger.warning(f"[STEP 3] Failed to fetch logo: status {_r.status_code}")
                except Exception as _e:
                    logger.warning(f"[STEP 3] Failed to fetch logo from URL: {_e}")

            # =================================================================
            # STEP 4: Build Gemini contents for image editing
            # =================================================================
            logger.info("[STEP 4] Building edit prompt...")

            contents = []

            # Source image as inline_data
            contents.append({
                "inline_data": {
                    "mime_type": source_mime,
                    "data": base64.b64encode(source_bytes).decode("utf-8"),
                }
            })

            # Edit instruction
            edit_instruction = (
                "EDIT THIS IMAGE according to the following instruction. "
                "Do NOT generate a completely new image — modify the existing image while preserving "
                "its overall composition, style, and elements that are not mentioned in the edit request.\n\n"
                f"EDIT INSTRUCTION: {modification_prompt}\n\n"
                "RULES:\n"
                "- Preserve all aspects of the image that are NOT mentioned in the edit instruction\n"
                "- Maintain the same overall composition and style\n"
                "- Make the edits look natural and seamlessly integrated\n"
                "- Do not add any new text unless specifically requested\n"
                "- Do not remove existing elements unless specifically requested"
            )
            contents.append(edit_instruction)

            # Optional logo
            if logo_bytes:
                _logo_mime = "image/jpeg" if logo_bytes[:3] == b'\xff\xd8\xff' else "image/png"
                contents.append({
                    "inline_data": {
                        "mime_type": _logo_mime,
                        "data": base64.b64encode(logo_bytes).decode("utf-8"),
                    }
                })
                contents.append(
                    "LOGO REFERENCE: Integrate this logo naturally into the edited image. "
                    "Do NOT alter the logo's colors, fonts, shapes, icons, or styling. "
                    "The only allowed operation is resizing/scaling."
                )

            # =================================================================
            # STEP 5: Call Gemini image model
            # =================================================================
            logger.info("[STEP 5] Calling Gemini for image edit...")

            temp = max(0.0, min(1.0, temperature if temperature is not None else 0.75))

            config = types.GenerateContentConfig(
                temperature=temp,
                response_modalities=["IMAGE"],
            )

            response = await gemini_client.aio.models.generate_content(
                model=image_model,
                contents=contents,
                config=config,
            )

            # Log token usage
            usage = response.usage_metadata
            logger.info(f"   Tokens: prompt={usage.prompt_token_count or '?'} output={usage.candidates_token_count or '?'}")

            # Extract image bytes (same pattern as marketingpost.py)
            if not response or not response.candidates or not response.candidates[0]:
                raise HTTPException(status_code=502, detail="No candidates returned from Gemini API")

            parts = response.parts if hasattr(response, "parts") else response.candidates[0].content.parts
            if parts is None:
                raise HTTPException(status_code=502, detail="No image data received from Gemini")

            edited_bytes = None
            out_mime = "image/png"
            for part in parts:
                if hasattr(part, "inline_data") and part.inline_data:
                    edited_bytes = part.inline_data.data
                    if hasattr(part.inline_data, "mime_type"):
                        out_mime = part.inline_data.mime_type
                    break

            if not edited_bytes:
                raise HTTPException(status_code=502, detail="No image bytes in Gemini response")

            # Get edited dimensions
            edited_pil = Image.open(BytesIO(edited_bytes))
            edited_w, edited_h = edited_pil.size
            logger.info(f"   Edited image: {edited_w}x{edited_h} ({len(edited_bytes)} bytes)")

            # Resize to original dimensions if they differ
            if (edited_w, edited_h) != (width, height):
                logger.info(f"   Resizing {edited_w}x{edited_h} -> {width}x{height} to match original")
                edited_pil = edited_pil.resize((width, height), Image.LANCZOS)
                buf = BytesIO()
                edited_pil.save(buf, format="PNG")
                edited_bytes = buf.getvalue()
                edited_w, edited_h = width, height

            # =================================================================
            # STEP 6: Optional caption generation
            # =================================================================
            caption_text = None
            hashtags_list = None

            if generate_caption and company_name:
                logger.info("[STEP 6] Generating caption for edited image...")
                try:
                    caption_prompt = (
                        f"You are a social media marketing expert. Generate a caption and hashtags for this image.\n\n"
                        f"Company: {company_name}\n"
                    )
                    if company_profile:
                        caption_prompt += f"About: {company_profile}\n"
                    caption_prompt += (
                        f"\nThe image was edited with this instruction: {modification_prompt}\n\n"
                        "Return JSON only:\n"
                        '{"caption": "your caption here", "hashtags": ["#tag1", "#tag2", ...]}\n'
                    )

                    caption_contents = [
                        {"inline_data": {"mime_type": out_mime, "data": base64.b64encode(edited_bytes).decode("utf-8")}},
                        caption_prompt,
                    ]

                    cap_response = await gemini_client.aio.models.generate_content(
                        model=gemini_model,
                        contents=caption_contents,
                    )

                    cap_text = cap_response.text.strip()
                    # Strip markdown fences if present
                    if cap_text.startswith("```"):
                        cap_text = re.sub(r"^```\w*\n?", "", cap_text)
                        cap_text = re.sub(r"\n?```$", "", cap_text)

                    cap_data = json.loads(cap_text)
                    caption_text = cap_data.get("caption")
                    hashtags_list = cap_data.get("hashtags", [])
                    logger.info(f"   Caption generated ({len(caption_text or '')} chars)")
                except Exception as e:
                    logger.warning(f"   Caption generation failed: {e}")

            # =================================================================
            # STEP 7: Save to disk
            # =================================================================
            logger.info("[STEP 7] Saving edited image...")

            timestamp_hex = uuid.uuid4().hex[:8]

            # Derive source identifier for folder naming
            if image_path:
                source_id = re.sub(r'[^\w]', '_', Path(image_path).stem)[:30]
            elif image_url:
                source_id = re.sub(r'[^\w]', '_', image_url.strip().split('/')[-1].split('.')[0])[:30]
            elif image_file and image_file.filename:
                source_id = re.sub(r'[^\w]', '_', Path(image_file.filename).stem)[:30]
            else:
                source_id = "upload"

            folder_name = f"regenerated/{source_id}_{timestamp_hex}"
            save_dir = storage_dir / folder_name
            save_dir.mkdir(parents=True, exist_ok=True)

            file_path = save_dir / "edited.png"
            with open(file_path, "wb") as f:
                f.write(edited_bytes)

            # Metadata sidecar
            metadata = {
                "version": "regenerate_v1",
                "source": source_label,
                "modification_prompt": modification_prompt,
                "temperature": temp,
                "original_dimensions": f"{width}x{height}",
                "edited_dimensions": f"{edited_w}x{edited_h}",
                "has_logo": bool(logo_bytes),
                "generated_at": datetime.now().isoformat(),
                "model": image_model,
                "file_size_bytes": len(edited_bytes),
                "caption": caption_text,
                "hashtags": hashtags_list,
            }

            metadata_file = file_path.with_suffix(".json")
            with open(metadata_file, "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)

            logger.info(f"   Saved: {save_dir}/")

            # =================================================================
            # STEP 8: Upload to Cloudinary
            # =================================================================
            logger.info("[STEP 8] Uploading to Cloudinary...")
            cloudinary_url = _upload_to_cloudinary(
                edited_bytes,
                folder=f"quicksocial/regenerated/{source_id}",
                public_id=timestamp_hex,
            )

            local_url = f"/images/{folder_name}/edited.png"
            image_url_final = cloudinary_url or local_url
            b64_preview = f"data:{out_mime};base64,{base64.b64encode(edited_bytes).decode('utf-8')}"

            metadata["image_url"] = image_url_final
            metadata["local_url"] = local_url

            logger.info(f"[DONE] Regeneration complete -> {image_url_final}")

            return RegenerateImageResponse(
                image_url=image_url_final,
                image_preview=b64_preview,
                original_image_url=source_label,
                modification_prompt=modification_prompt,
                caption=caption_text,
                hashtags=hashtags_list,
                metadata=metadata,
                original_metadata=original_metadata,
            )

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"[REGENERATE] Failed: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Image regeneration failed: {str(e)}")

    return router
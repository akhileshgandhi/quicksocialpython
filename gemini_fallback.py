"""
Gemini model fallback — retry generate_content with alternate models on transient API errors.

Use when a single model is overloaded (503), rate-limited (429), or temporarily unavailable.
Text and image generation use separate model lists because capabilities differ.
"""
from __future__ import annotations

import logging
from typing import Any, Optional, Sequence

logger = logging.getLogger(__name__)

# Primary-first order: stable lite → newer preview → full flash (text / multimodal text)
TEXT_MODEL_FALLBACK_CHAIN: tuple[str, ...] = (
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
    "gemini-3.1-flash-lite-preview",
)

# Image output models only — primary then fallback on transient API errors
IMAGE_MODEL_FALLBACK_CHAIN: tuple[str, ...] = (
    "gemini-3.1-flash-image-preview",
    "gemini-3-pro-image-preview",
)

try:
    from google.api_core import exceptions as _gexc

    _TRANSIENT_EXCEPTION_TYPES = tuple(
        getattr(_gexc, name)
        for name in (
            "ResourceExhausted",
            "ServiceUnavailable",
            "DeadlineExceeded",
            "InternalServerError",
            "TooManyRequests",
        )
        if isinstance(getattr(_gexc, name, None), type)
    )
except Exception:  # pragma: no cover
    _TRANSIENT_EXCEPTION_TYPES = ()


def is_transient_gemini_error(exc: BaseException) -> bool:
    """
    True if trying another model might succeed (overload, rate limit, transient server errors).
    False for client/auth/validation errors — caller should not mask those with fallback.
    """
    if _TRANSIENT_EXCEPTION_TYPES and isinstance(exc, _TRANSIENT_EXCEPTION_TYPES):
        return True

    status = getattr(exc, "status_code", None)
    if status is None:
        status = getattr(exc, "code", None)
    if status in (429, 500, 502, 503, 504):
        return True

    # google.genai / httpx sometimes expose HTTP status on nested response
    resp = getattr(exc, "response", None)
    if resp is not None:
        sc = getattr(resp, "status_code", None)
        if sc in (429, 500, 502, 503, 504):
            return True

    msg = str(exc).lower()
    for needle in (
        "503",
        "502",
        "429",
        "500",
        "504",
        "unavailable",
        "overloaded",
        "resource exhausted",
        "too many requests",
        "try again",
        "deadline exceeded",
        "timeout",
        "temporarily",
        "service unavailable",
    ):
        if needle in msg:
            return True

    # Explicit non-retry: bad request, auth, not found
    if status in (400, 401, 403, 404):
        return False
    if "400" in msg or "401" in msg or "403" in msg or "404" in msg:
        if "not found" in msg or "permission" in msg or "invalid" in msg or "api key" in msg:
            return False

    return False


async def aio_generate_content_with_fallback(
    client: Any,
    models: Sequence[str],
    *,
    contents: Any,
    config: Any = None,
) -> Any:
    """
    Async Gemini generate_content with model fallback (client.aio.models.generate_content).

    Tries each model in *models* until success. On non-transient errors, raises immediately.
    If all models fail with transient errors, raises the last exception.
    """
    if not models:
        raise ValueError("models sequence must not be empty")

    last_exc: Optional[BaseException] = None
    for i, model in enumerate(models):
        try:
            kwargs: dict[str, Any] = {"model": model, "contents": contents}
            if config is not None:
                kwargs["config"] = config
            return await client.aio.models.generate_content(**kwargs)
        except BaseException as e:
            last_exc = e
            if i + 1 < len(models) and is_transient_gemini_error(e):
                logger.warning(
                    "Gemini model %s failed (%s); trying fallback",
                    model,
                    type(e).__name__,
                )
                continue
            raise

    assert last_exc is not None
    raise last_exc


def sync_generate_content_with_fallback(
    client: Any,
    models: Sequence[str],
    *,
    contents: Any,
    config: Any = None,
) -> Any:
    """
    Sync Gemini generate_content with model fallback (client.models.generate_content).

    Used inside asyncio.to_thread(...) from scraper agents.
    """
    if not models:
        raise ValueError("models sequence must not be empty")

    last_exc: Optional[BaseException] = None
    for i, model in enumerate(models):
        try:
            kwargs: dict[str, Any] = {"model": model, "contents": contents}
            if config is not None:
                kwargs["config"] = config
            return client.models.generate_content(**kwargs)
        except BaseException as e:
            last_exc = e
            if i + 1 < len(models) and is_transient_gemini_error(e):
                logger.warning(
                    "Gemini model %s failed (%s); trying fallback",
                    model,
                    type(e).__name__,
                )
                continue
            raise

    assert last_exc is not None
    raise last_exc

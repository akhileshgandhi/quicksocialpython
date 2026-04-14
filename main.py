from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from google import genai
from pathlib import Path
import os
import sys
import logging
from dotenv import load_dotenv

from gemini_fallback import IMAGE_MODEL_FALLBACK_CHAIN, TEXT_MODEL_FALLBACK_CHAIN

# ================= MODULE IMPORTS =================
from campaign import create_campaign_router
from smartpost import create_smartpost_router
from scraper_agents import create_agentic_scraper_router
from prompt_enhancer import create_prompt_enhancer_router
from regenerate import create_regenerate_router

# ================= CONFIGURATION =================
load_dotenv()
sys.stdout.reconfigure(encoding='utf-8')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)

# Gemini API Configuration
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY environment variable is not set. Check your .env file.")
client = genai.Client(api_key=GEMINI_API_KEY)
# Ordered fallback lists (see gemini_fallback.py) — do not use a single model id here.

# Storage
STORAGE_DIR = Path("generated_images")
STORAGE_DIR.mkdir(exist_ok=True)

# ================= APP CREATION =================
app = FastAPI(
    title="Social Media Marketing Image Generator",
    description="Generate professional marketing post images using AI",
    version="3.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_origin_regex=(
        r"https?://(localhost|127\.0\.0\.1)(:\d+)?"          # local dev
        r"|https://[a-z0-9\-]+\.[a-z0-9\-]+\.devtunnels\.ms" # devtunnel (any region)
        r"|https://[a-z0-9\-]+\.devtunnels\.ms"              # devtunnel (short form)
    ),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

app.mount("/images", StaticFiles(directory=str(STORAGE_DIR)), name="images")

# ================= INCLUDE ROUTERS =================
app.include_router(create_campaign_router(client, TEXT_MODEL_FALLBACK_CHAIN, IMAGE_MODEL_FALLBACK_CHAIN, STORAGE_DIR))
app.include_router(create_smartpost_router(client, TEXT_MODEL_FALLBACK_CHAIN, IMAGE_MODEL_FALLBACK_CHAIN, STORAGE_DIR))
app.include_router(create_agentic_scraper_router(client, TEXT_MODEL_FALLBACK_CHAIN, STORAGE_DIR))
app.include_router(create_prompt_enhancer_router(client, TEXT_MODEL_FALLBACK_CHAIN))
app.include_router(create_regenerate_router(client, TEXT_MODEL_FALLBACK_CHAIN, IMAGE_MODEL_FALLBACK_CHAIN, STORAGE_DIR))


# ================= HEALTH CHECK =================
@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8055, reload=True)
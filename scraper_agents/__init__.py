"""
QuickSocial Agentic Scraper — parallel, AI-driven website scraping.

Exports create_agentic_scraper_router() with the same signature as
the original scraper.create_scraper_router() so it can be dropped in as
a replacement or mounted alongside the legacy endpoint.
"""

from scraper_agents.orchestrator import create_agentic_scraper_router

__all__ = ["create_agentic_scraper_router"]

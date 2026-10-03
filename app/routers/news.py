# app/routers/news.py

import os
import json
import hashlib
from datetime import datetime, date
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, BackgroundTasks
from pydantic import BaseModel

from app.llm.summarizer import NewsSummarizer

# ─────────────────────────────────────────────────────────────────────────────
# Router setup
# ─────────────────────────────────────────────────────────────────────────────
router = APIRouter(prefix="/news", tags=["News & Summaries"])

# Built lazily so the app (and tests) can import without OPENAI_API_KEY set
_summarizer: Optional[NewsSummarizer] = None

def _get_summarizer() -> NewsSummarizer:
    global _summarizer
    if _summarizer is None:
        if not os.getenv("OPENAI_API_KEY"):
            raise HTTPException(
                status_code=503,
                detail="News summaries unavailable: OPENAI_API_KEY is not set."
            )
        _summarizer = NewsSummarizer()
    return _summarizer

# ─────────────────────────────────────────────────────────────────────────────
# Simple in-memory cache (Redis-ready swap later)
# Key format: "news:{category}:{date}"  or  "dive:{hash(topic+category)}"
# ─────────────────────────────────────────────────────────────────────────────
_cache: dict[str, dict] = {}

def _cache_key_news(category: str) -> str:
    return f"news:{category.lower()}:{date.today().isoformat()}"

def _cache_key_dive(topic: str, category: str) -> str:
    raw = f"{topic.lower().strip()}:{category.lower().strip()}"
    return f"dive:{hashlib.md5(raw.encode()).hexdigest()}"

def _get_cache(key: str) -> Optional[dict]:
    return _cache.get(key)

def _set_cache(key: str, value: dict) -> None:
    _cache[key] = value

# ─────────────────────────────────────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────────────────────────────────────
class DeepDiveRequest(BaseModel):
    topic: str
    category: str

class NewsResponse(BaseModel):
    category: str
    summary: str
    articles: list[dict]
    generated_at: str
    cached: bool = False

class DeepDiveResponse(BaseModel):
    topic: str
    category: str
    overview: str
    generated_at: str
    cached: bool = False


# ─────────────────────────────────────────────────────────────────────────────
# GET /news/categories
# ─────────────────────────────────────────────────────────────────────────────
@router.get(
    "/categories",
    summary="List all available news categories",
)
async def get_categories():
    """
    Returns the list of categories supported for both
    daily news briefs and topic deep dives.
    """
    return {
        "categories": NewsSummarizer.available_categories(),
        "descriptions": {
            "general":    "Top world headlines",
            "technology": "Latest in tech, software, and innovation",
            "law":        "Legal news, court rulings, and policy",
            "philosophy": "Ideas, ethics, and philosophical discourse",
            "history":    "Historical discoveries and retrospectives",
            "psychology": "Mental health, behavior, and research",
            "maths":      "Mathematics, proofs, and discoveries",
            "geography":  "World geography, exploration, and nature",
        }
    }


# ─────────────────────────────────────────────────────────────────────────────
# GET /news/daily-brief
# ─────────────────────────────────────────────────────────────────────────────
@router.get(
    "/daily-brief",
    response_model=NewsResponse,
    summary="Get today's AI-generated news summary for a category",
)
async def get_daily_brief(
    category: str = Query(default="general", description="News category"),
):
    """
    Fetches the latest RSS articles for the given category and
    returns an AI-generated summary.

    - Results are **cached per day per category** so the LLM is only
      called once per day per category.
    - Subsequent requests return the cached version instantly.
    """
    category = category.lower().strip()
    valid = NewsSummarizer.available_categories()

    if category not in valid:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid category '{category}'. Valid options: {valid}"
        )

    # Check cache first
    cache_key = _cache_key_news(category)
    cached_result = _get_cache(cache_key)

    if cached_result:
        return NewsResponse(**cached_result, cached=True)

    # Not in cache — generate fresh
    summarizer = _get_summarizer()
    try:
        result = await summarizer.summarize_news(category)
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"Failed to generate news summary: {str(e)}"
        )

    # Store in cache
    _set_cache(cache_key, result)

    return NewsResponse(**result, cached=False)


# ─────────────────────────────────────────────────────────────────────────────
# POST /news/deep-dive
# ─────────────────────────────────────────────────────────────────────────────
@router.post(
    "/deep-dive",
    response_model=DeepDiveResponse,
    summary="Get an AI-generated deep dive on any topic",
)
async def get_deep_dive(body: DeepDiveRequest):
    """
    Generates a structured 150-200 word overview on any topic within
    a given category.

    Example request:
    ```json
    {
        "topic": "Stoicism",
        "category": "philosophy"
    }
    ```

    - Results are **cached per topic+category combo** (no expiry — topic
      knowledge doesn't change hourly).
    - Great for on-demand learning during the day.
    """
    topic    = body.topic.strip()
    category = body.category.lower().strip()

    if not topic:
        raise HTTPException(status_code=400, detail="Topic cannot be empty.")

    valid = NewsSummarizer.available_categories()
    if category not in valid:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid category '{category}'. Valid options: {valid}"
        )

    # Check cache
    cache_key = _cache_key_dive(topic, category)
    cached_result = _get_cache(cache_key)

    if cached_result:
        return DeepDiveResponse(**cached_result, cached=True)

    # Generate
    summarizer = _get_summarizer()
    try:
        result = await summarizer.topic_deep_dive(topic, category)
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"Failed to generate deep dive: {str(e)}"
        )

    # Cache result
    _set_cache(cache_key, result)

    return DeepDiveResponse(**result, cached=False)


# ─────────────────────────────────────────────────────────────────────────────
# DELETE /news/cache  (dev/admin utility)
# ─────────────────────────────────────────────────────────────────────────────
@router.delete(
    "/cache",
    summary="Clear the news cache (dev use)",
)
async def clear_cache():
    """
    Clears the entire in-memory news cache.
    Useful during development or if you want to force-refresh summaries.
    """
    count = len(_cache)
    _cache.clear()
    return {"cleared_entries": count, "timestamp": datetime.now().isoformat()}

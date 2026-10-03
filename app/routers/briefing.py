from fastapi import APIRouter, HTTPException, Depends
from typing import List, Dict, Any
import httpx
import os
from app.llm.agent import summarize_text # Assuming you'll add this function

router = APIRouter(
    prefix="/briefing",
    tags=["Briefing & Summaries"]
)

# --- Configuration for external APIs ---
# You'll need to sign up for a news API (e.g., NewsAPI, GNews, or use a general web search API)
NEWS_API_KEY = os.getenv("NEWS_API_KEY", "YOUR_NEWS_API_KEY") # Get a real key!
NEWS_API_URL = "https://newsapi.org/v2/top-headlines" # Example for NewsAPI

# --- Helper to fetch news ---
async def fetch_top_news(country: str = "us", category: str = "general") -> List[Dict]:
    if not NEWS_API_KEY or NEWS_API_KEY == "YOUR_NEWS_API_KEY":
        raise HTTPException(status_code=500, detail="NEWS_API_KEY not configured.")
    
    params = {
        "country": country,
        "category": category,
        "apiKey": NEWS_API_KEY,
        "pageSize": 5 # Get top 5 articles
    }
    async with httpx.AsyncClient() as client:
        response = await client.get(NEWS_API_URL, params=params)
        response.raise_for_status()
        articles = response.json().get("articles", [])
        return [{"title": a["title"], "description": a["description"], "url": a["url"]} for a in articles if a["title"] and a["description"]]

# --- Helper to perform web search for topic summary ---
# For a production app, consider a dedicated search API like SerpAPI, Google Custom Search, etc.
# For now, we'll simulate or use a very basic search if available.
async def search_web_for_topic(query: str) -> str:
    # Placeholder: In a real app, integrate with a search API
    # Example using unified_search (which I don't have direct access to run here, but you would use it)
    # For demonstration, we'll return a static value or use a simple LLM query
    
    # You would integrate your actual web search tool here
    # E.g., results = await unified_search_tool(query)
    # Then extract relevant text.
    
    # For now, let's assume we get some content
    return f"Simulated search results for '{query}': Information about {query} from various sources suggests..."


@router.get("/daily-news-summary")
async def get_daily_news_summary() -> Dict:
    """Provides a summary of top daily news headlines."""
    try:
        articles = await fetch_top_news()
        if not articles:
            return {"summary": "Could not fetch daily news at this time.", "articles": []}
        
        # Combine article titles and descriptions for summarization
        news_text = "\n\n".join([f"Title: {a['title']}\nDescription: {a['description']}" for a in articles])
        
        # Use your LLM to summarize
        # You need to implement summarize_text in app.llm.agent.py
        summary = summarize_text(news_text, prompt="Summarize these news articles into a concise daily briefing, highlighting key developments.")
        
        return {
            "summary": summary,
            "articles": articles
        }
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=f"News API error: {e.response.text}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get daily news summary: {str(e)}")

@router.get("/topic-summary")
async def get_topic_summary(topic: str, subject_area: str) -> Dict:
    """Provides a summary on a specified topic from a given subject area."""
    try:
        # Perform web search or query a knowledge base
        search_query = f"{topic} in {subject_area}"
        raw_content = await search_web_for_topic(search_query) # Integrate real search here

        if not raw_content:
            return {"summary": f"Could not find information on '{topic}' in '{subject_area}'.", "topic": topic, "subject_area": subject_area}

        # Use your LLM to summarize the content
        # You need to implement summarize_text in app.llm.agent.py
        summary = summarize_text(raw_content, prompt=f"Summarize the following information about '{topic}' from the perspective of '{subject_area}'.")
        
        return {
            "topic": topic,
            "subject_area": subject_area,
            "summary": summary
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get topic summary: {str(e)}")

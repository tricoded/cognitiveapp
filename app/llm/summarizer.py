# app/llm/summarizer.py

import os
import asyncio
import feedparser
from datetime import datetime
from typing import Optional

from langchain_openai import ChatOpenAI           # ✅ new import path (not deprecated)
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

# ─────────────────────────────────────────────────────────────────────────────
# RSS feeds per category
# ─────────────────────────────────────────────────────────────────────────────
FEEDS: dict[str, str] = {
    "technology":  "https://feeds.arstechnica.com/arstechnica/index",
    "law":         "https://feeds.law.com/law/news",
    "philosophy":  "https://philosophynow.org/feed",
    "history":     "https://www.smithsonianmag.com/rss/history-archaeology/",
    "psychology":  "https://www.psychologytoday.com/intl/front-page/feed",
    "maths":       "https://www.quantamagazine.org/feed/",
    "geography":   "https://www.nationalgeographic.com/feed/all",
    "general":     "https://feeds.bbci.co.uk/news/rss.xml",
}

# ─────────────────────────────────────────────────────────────────────────────
# Prompts
# ─────────────────────────────────────────────────────────────────────────────
NEWS_SUMMARY_PROMPT = ChatPromptTemplate.from_template("""
You are a concise, intelligent news summarizer for a personal productivity assistant called Cognitive.

Your job:
1. Read the following news headlines and snippets
2. Write a 3-5 sentence summary covering the most important developments
3. Be clear, factual, and insightful
4. End with one sentence on why this matters to the reader

Category: {category}

Articles:
{articles}

Summary:
""")

TOPIC_DEEP_DIVE_PROMPT = ChatPromptTemplate.from_template("""
You are a knowledgeable tutor summarizing a topic for a curious student.

Topic: {topic}
Category: {category}

Write a structured 150-200 word overview that includes:
- A clear definition or core concept
- Why it matters today
- One fascinating fact or recent development
- A suggestion for what to explore next

Overview:
""")


# ─────────────────────────────────────────────────────────────────────────────
# NewsSummarizer
# ─────────────────────────────────────────────────────────────────────────────
class NewsSummarizer:
    def __init__(self, api_key: Optional[str] = None):
        self.llm = ChatOpenAI(
            api_key=api_key or os.getenv("OPENAI_API_KEY"),
            model="gpt-4-turbo",
            temperature=0.3,
        )
        self.parser = StrOutputParser()

        # ✅ Using modern LCEL chains (LLMChain is deprecated)
        self.news_chain       = NEWS_SUMMARY_PROMPT   | self.llm | self.parser
        self.deepdive_chain   = TOPIC_DEEP_DIVE_PROMPT | self.llm | self.parser

    # ─────────────────────────────────────────────────────────────────────
    # Fetch RSS articles (runs in threadpool since feedparser is sync)
    # ─────────────────────────────────────────────────────────────────────
    async def fetch_articles(self, category: str) -> list[dict]:
        """
        Fetch top 5 articles from the RSS feed for a given category.
        Falls back to 'general' if category is unknown.
        """
        feed_url = FEEDS.get(category.lower(), FEEDS["general"])

        # feedparser is blocking — run in executor so we don't block event loop
        loop = asyncio.get_event_loop()
        feed = await loop.run_in_executor(None, feedparser.parse, feed_url)

        articles = []
        for entry in feed.entries[:5]:
            articles.append({
                "title":     entry.get("title", "No title"),
                "link":      entry.get("link", "#"),
                "snippet":   entry.get("summary", "")[:250].strip(),
                "published": entry.get("published", ""),
            })

        return articles

    # ─────────────────────────────────────────────────────────────────────
    # Daily news summary for a category
    # ─────────────────────────────────────────────────────────────────────
    async def summarize_news(self, category: str = "general") -> dict:
        """
        Fetch articles and generate an AI summary for a category.
        Used for the morning news brief feature.
        """
        articles = await self.fetch_articles(category)

        if not articles:
            return {
                "category":     category,
                "summary":      "No articles found for this category right now.",
                "articles":     [],
                "generated_at": datetime.now().isoformat(),
            }

        # Build text block from articles
        articles_text = "\n".join([
            f"- [{a['title']}]: {a['snippet']}"
            for a in articles
        ])

        # Run LLM chain
        summary = await self.news_chain.ainvoke({
            "category": category,
            "articles": articles_text,
        })

        return {
            "category":     category,
            "summary":      summary.strip(),
            "articles":     articles,
            "generated_at": datetime.now().isoformat(),
        }

    # ─────────────────────────────────────────────────────────────────────
    # On-demand topic deep dive (law, maths, philosophy, etc.)
    # ─────────────────────────────────────────────────────────────────────
    async def topic_deep_dive(self, topic: str, category: str) -> dict:
        """
        Generate a structured mini-lesson on any topic.
        Used for the 'Learn about X' feature.
        """
        overview = await self.deepdive_chain.ainvoke({
            "topic":    topic,
            "category": category,
        })

        return {
            "topic":        topic,
            "category":     category,
            "overview":     overview.strip(),
            "generated_at": datetime.now().isoformat(),
        }

    # ─────────────────────────────────────────────────────────────────────
    # List available categories
    # ─────────────────────────────────────────────────────────────────────
    @staticmethod
    def available_categories() -> list[str]:
        return list(FEEDS.keys())

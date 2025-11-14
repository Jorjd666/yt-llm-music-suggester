from typing import List, Dict, Any
from .config import settings
from .logger import logger

from openai import OpenAI
import json

def _openai_client():
    return OpenAI(api_key=settings.OPENAI_API_KEY)

def _format_prompt(genre: str, mood: str | None, era: str | None, language: str | None, candidates: List[Dict[str, Any]], limit: int):
    lines = []
    lines.append("You are a helpful music curator. Given YouTube candidate videos, return a final JSON list of the top picks.")
    lines.append("Goals: diversity, quality (official videos preferred), matching genre/mood/era/language if provided.")
    lines.append(f"Genre: {genre}")
    if mood: lines.append(f"Mood: {mood}")
    if era: lines.append(f"Era: {era}")
    if language: lines.append(f"Language preference: {language}")
    lines.append(f"Limit: {limit}")
    lines.append("Candidates:")
    for c in candidates:
        lines.append(f"- title={c.get('title')} | channel={c.get('channelTitle')} | videoId={c.get('videoId')} | publishedAt={c.get('publishedAt')}")
    lines.append("Return ONLY valid JSON: [{title, videoId, channelTitle, url, reason, tags, publishedAt}]")
    return "\n".join(lines)

def _with_defaults(items: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    out = []
    for it in items[:limit]:
        out.append({
            "title": it.get("title"),
            "videoId": it.get("videoId"),
            "channelTitle": it.get("channelTitle"),
            "url": it.get("url"),
            "reason": it.get("reason") or "",
            "tags": it.get("tags") or [],
            "publishedAt": it.get("publishedAt"),
        })
    return out

def rerank_with_llm(genre: str, mood: str | None, era: str | None, language: str | None, candidates: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    # If LLM disabled, just return candidates with safe defaults
    if settings.LLM_PROVIDER.lower() == "none":
        logger.info("LLM_PROVIDER=none, bypassing rerank; truncating candidates.")
        return _with_defaults(candidates, limit)

    if settings.LLM_PROVIDER.lower() != "openai":
        raise ValueError("Only 'openai' or 'none' are supported in this template.")

    prompt = _format_prompt(genre, mood, era, language, candidates, limit)
    client = _openai_client()

    try:
        completion = client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "You are a precise JSON generator."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.4,
            max_tokens=700,
            response_format={"type": "json_object"},
        )
        content = completion.choices[0].message.content
        obj = json.loads(content)
        if isinstance(obj, list):
            items = obj
        else:
            items = obj.get("items") or obj.get("suggestions") or obj.get("data") or []
        return _with_defaults(items, limit)
    except Exception as e:
        logger.error(f"LLM rerank failed or returned invalid JSON: {e}. Falling back to candidates.")
        # Fallback: return candidates with safe defaults (prevents 500)
        return _with_defaults(candidates, limit)

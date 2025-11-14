
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from .config import settings
from .logger import logger
from .schemas import SuggestRequest, SuggestResponse, Suggestion
from .youtube_client import search_music_videos
from .llm_client import rerank_with_llm

app = FastAPI(title="yt-llm-music-suggester", version="1.0.0")
limiter = Limiter(key_func=get_remote_address, default_limits=[settings.RATE_LIMIT])
app.state.limiter = limiter

@app.exception_handler(RateLimitExceeded)
def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded. Please try again later."})

@app.get("/healthz")
async def healthz():
    return {"status": "ok"}

@app.post("/suggest", response_model=SuggestResponse)
@limiter.limit(settings.RATE_LIMIT)
async def suggest(req: SuggestRequest, request: Request):
    if not settings.YOUTUBE_API_KEY:
        raise HTTPException(status_code=500, detail="YOUTUBE_API_KEY not configured")
    if settings.LLM_PROVIDER.lower() == "openai" and not settings.OPENAI_API_KEY:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY not configured for LLM rerank")

    # Compose YouTube query
    terms = [req.genre]
    if req.mood: terms.append(req.mood)
    if req.era: terms.append(req.era)
    if req.language: terms.append(req.language)
    query = " ".join(terms)

    yt_data = await search_music_videos(
        query=query,
        max_results=min(settings.MAX_YT_RESULTS, max(5, req.limit or 10)),
        timeout=settings.REQUESTS_TIMEOUT,
    )
    items = yt_data.get("items", [])

    # Normalize candidates
    candidates = []
    for it in items:
        s = it.get("snippet", {})
        vid = it.get("id", {}).get("videoId")
        if not vid:
            continue
        candidates.append({
            "title": s.get("title"),
            "videoId": vid,
            "channelTitle": s.get("channelTitle"),
            "url": f"https://www.youtube.com/watch?v={vid}",
            "publishedAt": s.get("publishedAt"),
        })

    if not candidates:
        raise HTTPException(status_code=404, detail="No candidates found from YouTube")

    final = rerank_with_llm(
        genre=req.genre,
        mood=req.mood,
        era=req.era,
        language=req.language,
        candidates=candidates,
        limit=min(settings.MAX_SUGGESTIONS, req.limit or 10),
    )

    # Coerce into schema
    suggestions = [Suggestion(**s) for s in final if s.get("videoId")]
    resp = SuggestResponse(
        suggestions=suggestions,
        source_counts={"youtube_candidates": len(candidates), "llm_ranked": len(suggestions)},
    )
    logger.info(f"Responding with {len(suggestions)} suggestions")
    return resp

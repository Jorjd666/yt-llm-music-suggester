
from fastapi import FastAPI, Request, Header, Depends, HTTPException
import os
from prometheus_fastapi_instrumentator import Instrumentator
from fastapi.responses import JSONResponse, HTMLResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from .config import settings
from .logger import logger
from .schemas import SuggestRequest, SuggestResponse, Suggestion
from .youtube_client import search_music_videos
from .llm_client import rerank_with_llm

app = FastAPI(title="yt-llm-music-suggester", version="1.0.0")

# Prometheus metrics – add middleware BEFORE app starts
try:
    from prometheus_fastapi_instrumentator import Instrumentator
    if not getattr(app.state, "metrics_instrumented", False):
        Instrumentator().instrument(app).expose(app, endpoint="/metrics")
        app.state.metrics_instrumented = True
except Exception as e:
    logger.warning(f"Metrics disabled: {e}")

limiter = Limiter(key_func=get_remote_address, default_limits=[settings.RATE_LIMIT])
app.state.limiter = limiter

def require_api_token(authorization: str = Header(default="")):
    """
    Enforce Bearer token only if API_TOKEN is set.
    - 401 if header missing
    - 403 if token wrong
    """
    expected = os.getenv("API_TOKEN")
    if not expected:
        return  # auth disabled if no token set

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")

    token = authorization.split(" ", 1)[1].strip()
    if token != expected:
        raise HTTPException(status_code=403, detail="Invalid token")

@app.exception_handler(RateLimitExceeded)
def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded. Please try again later."})

@app.get("/healthz")
async def healthz():
    return {"status": "ok"}

@app.get("/", response_class=HTMLResponse)
async def index():
    return """
<!doctype html><meta charset="utf-8">
<title>YT LLM Music Suggester</title>
<style>body{font-family:system-ui;margin:2rem;max-width:780px} input,select,button{padding:.5rem;margin:.25rem}</style>
<h1>YT LLM Music Suggester</h1>
<div>
  <input id="genre" placeholder="genre (e.g., lofi)" value="lofi">
  <input id="mood"  placeholder="mood (e.g., chill)" value="chill">
  <input id="era"   placeholder="era (e.g., modern)">
  <input id="lang"  placeholder="language (e.g., en)">
  <input id="limit" type="number" min="1" max="25" value="5">
  <button onclick="go()">Suggest</button>
</div>
<pre id="out"></pre>
<script>
async function go(){
  const body = {
    genre:  document.getElementById('genre').value,
    mood:   document.getElementById('mood').value || null,
    era:    document.getElementById('era').value || null,
    language: document.getElementById('lang').value || null,
    limit:  parseInt(document.getElementById('limit').value || '5', 10)
  };
  const headers = {'Content-Type':'application/json'};
  const token = localStorage.getItem('apiToken');
  if (token) headers['Authorization'] = 'Bearer ' + token;
  const r = await fetch('/suggest', {method:'POST', headers, body: JSON.stringify(body)});
  document.getElementById('out').textContent = await r.text();
}
// simple token prompt once
if (!localStorage.getItem('apiToken')) {
  const t = prompt("API token (optional, press cancel if none)");
  if (t) localStorage.setItem('apiToken', t);
}
</script>
"""

@app.post("/suggest", response_model=SuggestResponse, dependencies=[Depends(require_api_token)])
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

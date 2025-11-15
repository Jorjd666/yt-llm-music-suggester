from fastapi import FastAPI, Request, Header, Depends, HTTPException
from fastapi.responses import JSONResponse, HTMLResponse
import os

from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from prometheus_fastapi_instrumentator import Instrumentator

from .config import settings
from .logger import logger
from .schemas import SuggestRequest, SuggestResponse, Suggestion
from .youtube_client import search_music_videos
from .llm_client import rerank_with_llm


app = FastAPI(title="yt-llm-music-suggester", version="1.0.0")

# ---- Prometheus metrics: instrument before app starts (idempotent) ----
try:
    if not getattr(app.state, "metrics_instrumented", False):
        Instrumentator().instrument(app).expose(app, endpoint="/metrics")
        app.state.metrics_instrumented = True
except Exception as e:
    logger.warning(f"Metrics disabled: {e}")

# ---- Rate limiting ----
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
    return JSONResponse(
        status_code=429,
        content={"detail": "Rate limit exceeded. Please try again later."},
    )


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


# ---- Tiny browser UI (no build tools, lives in this file) ----
@app.get("/", response_class=HTMLResponse)
async def index():
    return """
<!doctype html><meta charset="utf-8">
<title>YT LLM Music Suggester</title>
<meta name="viewport" content="width=device-width, initial-scale=1" />
<style>
  :root { color-scheme: light dark; }
  body{font-family:system-ui, -apple-system, Segoe UI, Roboto, Arial; margin:2rem; max-width:980px}
  header{margin-bottom:1rem}
  input,button{padding:.6rem .7rem; margin:.25rem .35rem .25rem 0; border-radius:8px; border:1px solid #ccc; min-width:12ch}
  button{cursor:pointer}
  .row{display:flex; flex-wrap:wrap; gap:.5rem; align-items:center}
  .muted{color:#666; font-size:.9rem}
  .grid{display:grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap:12px; margin-top:1rem}
  .card{border:1px solid #e5e5e5; border-radius:12px; overflow:hidden; box-shadow:0 1px 2px rgba(0,0,0,.05)}
  .card .body{padding:10px 12px}
  .title{font-weight:600; line-height:1.25}
  .title a{text-decoration:none}
  .meta{color:#666; font-size:.85rem; margin:.25rem 0 .5rem}
  .reason{font-size:.9rem}
  .error{color:#b00020}
  img{display:block; width:100%; height:auto}
  .topbar{display:flex; justify-content:space-between; align-items:center; gap:.75rem}
  .token{min-width: 280px;}
</style>
<header class="topbar">
  <div>
    <h2 style="margin:0">🎵 YT LLM Music Suggester</h2>
    <div class="muted">Enter a genre/mood and get ranked YouTube picks via the LLM.</div>
  </div>
  <div>
    <input id="token" class="token" placeholder="API token (optional)" />
    <button onclick="saveToken()">Save token</button>
  </div>
</header>

<div class="row">
  <input id="genre" placeholder="genre (e.g., lofi)" value="lofi">
  <input id="mood"  placeholder="mood (e.g., chill)" value="chill">
  <input id="era"   placeholder="era (e.g., 90s)">
  <input id="lang"  placeholder="language (e.g., en)">
  <input id="limit" type="number" min="1" max="25" value="5" style="width:7ch">
  <button id="go">Suggest</button>
</div>

<div id="status" class="muted" style="margin-top:.5rem"></div>
<div id="results" class="grid"></div>

<script>
function saveToken(){
  const t = document.getElementById('token').value.trim();
  if (t) localStorage.setItem('apiToken', t);
  else localStorage.removeItem('apiToken');
  document.getElementById('status').textContent = t ? 'Token saved in browser (localStorage)' : 'Token cleared';
}
(function preloadToken(){
  const t = localStorage.getItem('apiToken');
  if (t) document.getElementById('token').value = t;
})();

async function suggest(){
  const genre = document.getElementById('genre').value || 'lofi';
  const mood  = document.getElementById('mood').value || null;
  const era   = document.getElementById('era').value || null;
  const language = document.getElementById('lang').value || null;
  const limit = parseInt(document.getElementById('limit').value || '5', 10);

  const status = document.getElementById('status');
  const results = document.getElementById('results');
  status.textContent = 'Searching…';
  results.innerHTML = '';

  try {
    const headers = {'Content-Type':'application/json'};
    const token = localStorage.getItem('apiToken');
    if (token) headers['Authorization'] = 'Bearer ' + token;

    const resp = await fetch('/suggest', {
      method: 'POST',
      headers,
      body: JSON.stringify({ genre, mood, era, language, limit })
    });

    const text = await resp.text();
    if (!resp.ok) {
      status.innerHTML = '<span class="error">Error ' + resp.status + ': ' + text + '</span>';
      return;
    }
    const data = JSON.parse(text);
    const list = data.suggestions || [];
    status.textContent = 'Got ' + list.length + ' suggestion(s)';

    for (const s of list) {
      const vid = s.videoId;
      const thumb = vid ? 'https://img.youtube.com/vi/' + vid + '/hqdefault.jpg' : '';
      const card = document.createElement('div');
      card.className = 'card';
      card.innerHTML = `
        ${thumb ? `<a href="${s.url}" target="_blank" rel="noopener"><img src="${thumb}" alt="thumbnail"></a>` : ''}
        <div class="body">
          <div class="title"><a href="${s.url}" target="_blank" rel="noopener">${s.title || ''}</a></div>
          <div class="meta">${s.channelTitle || ''}${s.publishedAt ? ' · ' + s.publishedAt : ''}</div>
          ${s.reason ? `<div class="reason">Reason: ${s.reason}</div>` : ''}
        </div>`;
      results.appendChild(card);
    }
  } catch (e) {
    status.innerHTML = '<span class="error">Request failed: ' + e + '</span>';
  }
}
document.getElementById('go').addEventListener('click', suggest);
</script>
"""


@app.post("/suggest", response_model=SuggestResponse, dependencies=[Depends(require_api_token)])
@limiter.limit(settings.RATE_LIMIT)
async def suggest(req: SuggestRequest, request: Request):
    if not settings.YOUTUBE_API_KEY:
        raise HTTPException(status_code=500, detail="YOUTUBE_API_KEY not configured")
    if settings.LLM_PROVIDER.lower() == "openai" and not settings.OPENAI_API_KEY:
        # Only require OPENAI_API_KEY when provider=openai; Ollama works with OPENAI_BASE_URL+API_KEY placeholder
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY not configured for LLM rerank")

    # Compose YouTube query
    terms = [req.genre]
    if req.mood: terms.append(req.mood)
    if req.era: terms.append(req.era)
    if req.language: terms.append(req.language)
    query = " ".join(terms)

    # YouTube search
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

    # LLM rerank (OpenAI or Ollama-compatible)
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

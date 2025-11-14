
import httpx
from tenacity import retry, wait_exponential, stop_after_attempt
from .config import settings
from .logger import logger

YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"

@retry(wait=wait_exponential(min=1, max=8), stop=stop_after_attempt(3))
async def search_music_videos(query: str, max_results: int = 25, timeout: int = 10):
    params = {
        "key": settings.YOUTUBE_API_KEY,
        "part": "snippet",
        "type": "video",
        "videoCategoryId": "10",  # Music
        "maxResults": max_results,
        "q": query,
        "relevanceLanguage": "en",
        "safeSearch": "moderate",
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.get(YOUTUBE_SEARCH_URL, params=params)
        r.raise_for_status()
        data = r.json()
        logger.info(f"YouTube search returned {len(data.get('items', []))} items for query='{query}'")
        return data

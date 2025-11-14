
from pydantic import BaseModel, Field
from typing import List, Optional

class SuggestRequest(BaseModel):
    genre: str = Field(..., min_length=1, description="Primary genre (e.g., 'rock', 'lofi')")
    mood: Optional[str] = Field(None, description="Optional mood (e.g., 'chill', 'energetic')")
    era: Optional[str] = Field(None, description="Optional era (e.g., '90s', 'modern')")
    language: Optional[str] = Field(None, description="Preferred language (e.g., 'en', 'es')")
    limit: Optional[int] = Field(10, ge=1, le=25, description="Number of suggestions desired")

class Suggestion(BaseModel):
    title: str
    videoId: str
    channelTitle: str
    url: str
    reason: str
    tags: List[str] = []
    publishedAt: Optional[str] = None

class SuggestResponse(BaseModel):
    suggestions: List[Suggestion]
    source_counts: dict

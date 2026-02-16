import datetime as dt
import concurrent.futures
import threading
import time
from pathlib import Path

from fastapi import FastAPI, Query, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.models import AnalyzeResponse
from app.services.scoring import analyze_trend
from app.services.social_fetcher import (
    fetch_trends,
    get_available_categories,
    normalize_category,
)

app = FastAPI(
    title="TrendTruth",
    description="Social trend credibility analyzer for hackathons.",
    version="1.0.0",
)
BUILD_ID = "2026-02-15-ui-v3-5"

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

_cache_lock = threading.Lock()
_analysis_cache: dict[str, dict[str, object]] = {}
CACHE_TTL_SECONDS = 180


@app.middleware("http")
async def no_cache_middleware(request: Request, call_next):
    response = await call_next(request)
    if (
        request.url.path == "/"
        or request.url.path.startswith("/static/")
        or request.url.path.startswith("/api/")
        or request.url.path == "/__build"
    ):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


def _fresh_payload(limit: int, category: str, query: str) -> AnalyzeResponse:
    normalized_category = normalize_category(category)
    trends, source_health = fetch_trends(limit=limit, category=normalized_category, query=query)
    analyzed = []
    if trends:
        max_workers = min(8, max(2, len(trends)))
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            analyzed = list(executor.map(analyze_trend, trends))
    analyzed.sort(
        key=lambda item: (
            item.verdict == "High Risk",
            item.fake_probability,
            item.spread_index,
        ),
        reverse=True,
    )
    return AnalyzeResponse(
        generated_at=dt.datetime.now(dt.timezone.utc).isoformat(),
        analyzed_count=len(analyzed),
        selected_category=normalized_category,
        available_categories=[entry["id"] for entry in get_available_categories()],
        source_health=source_health,
        results=analyzed,
    )


@app.get("/api/analyze", response_model=AnalyzeResponse)
def analyze(
    limit: int = Query(20, ge=5, le=40),
    category: str = Query("all"),
    query: str = Query("", max_length=120),
    refresh: bool = Query(False),
) -> AnalyzeResponse:
    normalized_category = normalize_category(category)
    normalized_query = query.strip().lower()
    cache_key = f"{normalized_category}:{limit}:{normalized_query}"
    with _cache_lock:
        now = time.time()
        cache_bucket = _analysis_cache.get(cache_key, {})
        cached_payload = cache_bucket.get("payload")
        cached_at = float(cache_bucket.get("generated_at", 0.0))
        if (
            not refresh
            and cached_payload is not None
            and (now - cached_at) <= CACHE_TTL_SECONDS
        ):
            return cached_payload  # type: ignore[return-value]

    payload = _fresh_payload(limit=limit, category=normalized_category, query=normalized_query)
    with _cache_lock:
        _analysis_cache[cache_key] = {
            "generated_at": time.time(),
            "payload": payload,
        }
    return payload


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/__build")
def build_info() -> dict[str, str]:
    return {"build_id": BUILD_ID}

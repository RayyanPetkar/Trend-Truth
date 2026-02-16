import datetime as dt
import concurrent.futures
import html
import hashlib
import os
import re
import threading
import time
import urllib.parse
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from typing import Any

import requests

from app.models import TrendItem

CATEGORY_ORDER = [
    "all",
    "local",
    "india",
    "world",
    "entertainment",
    "health",
    "trending",
    "sports",
    "esports",
    "food",
    "events",
]

CATEGORY_LABELS = {
    "all": "All",
    "local": "Local",
    "india": "India",
    "world": "World",
    "entertainment": "Entertainment",
    "health": "Health",
    "trending": "Trending",
    "sports": "Sports",
    "esports": "Esports",
    "food": "Food",
    "events": "Events",
}

CATEGORY_QUERIES = {
    "local": "local city news breaking updates",
    "india": "India breaking news latest updates",
    "world": "world breaking news latest updates",
    "entertainment": "entertainment celebrity movie music news",
    "health": "health medical public health news",
    "trending": "viral trending breaking news social media",
    "sports": "sports breaking scores tournaments news",
    "esports": "esports tournament gaming league news",
    "food": "food restaurant culinary agriculture news",
    "events": "events festival conference live updates",
}

DEFAULT_REDDIT_SUBREDDITS = [
    "worldnews",
    "news",
    "technology",
    "science",
    "business",
    "politics",
]

CATEGORY_REDDIT_SUBREDDITS = {
    "local": ["news", "usanews"],
    "india": ["india", "indianews"],
    "world": ["worldnews", "news", "geopolitics"],
    "entertainment": ["entertainment", "movies", "television"],
    "health": ["health", "medicine", "science"],
    "trending": ["news", "worldnews", "technology", "sports"],
    "sports": ["sports", "soccer", "cricket", "nba"],
    "esports": ["esports", "valorant", "globaloffensive", "leagueoflegends"],
    "food": ["food", "cooking", "recipes"],
    "events": ["news", "events", "worldnews"],
}

CATEGORY_HINT_BY_SUBREDDIT = {
    "worldnews": "world",
    "news": "local",
    "usanews": "local",
    "india": "india",
    "indianews": "india",
    "entertainment": "entertainment",
    "movies": "entertainment",
    "television": "entertainment",
    "health": "health",
    "medicine": "health",
    "sports": "sports",
    "soccer": "sports",
    "cricket": "sports",
    "nba": "sports",
    "esports": "esports",
    "valorant": "esports",
    "globaloffensive": "esports",
    "leagueoflegends": "esports",
    "food": "food",
    "cooking": "food",
    "recipes": "food",
    "events": "events",
}

CATEGORY_KEYWORDS = {
    "india": {"india", "delhi", "mumbai", "bengaluru", "new delhi", "kolkata"},
    "world": {"world", "global", "europe", "asia", "middle east", "africa"},
    "entertainment": {"movie", "music", "actor", "actress", "hollywood", "bollywood"},
    "health": {"health", "medical", "disease", "vaccine", "hospital", "doctor"},
    "sports": {"sports", "match", "league", "tournament", "goal", "cricket", "nba", "nfl"},
    "esports": {"esports", "valorant", "cs2", "counter-strike", "dota", "league of legends"},
    "food": {"food", "restaurant", "chef", "recipe", "culinary", "dining"},
    "events": {"festival", "summit", "conference", "event", "expo", "concert"},
    "local": {"local", "county", "city council", "statewide", "community"},
}

X_QUERY_BY_CATEGORY = {
    "local": "(local news OR city updates) lang:en -is:retweet",
    "india": "(India news OR India breaking) lang:en -is:retweet",
    "world": "(world news OR global breaking) lang:en -is:retweet",
    "entertainment": "(entertainment OR celebrity OR movie release) lang:en -is:retweet",
    "health": "(health news OR medical update OR WHO) lang:en -is:retweet",
    "trending": "(news OR breaking OR viral) lang:en -is:retweet",
    "sports": "(sports OR match OR finals) lang:en -is:retweet",
    "esports": "(esports OR valorant OR cs2 OR dota2) lang:en -is:retweet",
    "food": "(food news OR restaurant OR culinary) lang:en -is:retweet",
    "events": "(event update OR festival OR conference) lang:en -is:retweet",
}

NITTER_INSTANCES = [
    "https://nitter.net",
    "https://nitter.privacydev.net",
]

NITTER_ACCOUNTS_BY_CATEGORY = {
    "india": ["ndtv", "ANI", "the_hindu"],
    "world": ["Reuters", "BBCWorld", "AP"],
    "entertainment": ["Variety", "RollingStone"],
    "health": ["WHO", "CDCgov"],
    "sports": ["espn", "SkySportsNews"],
    "esports": ["ESPN_Esports", "Dexerto"],
    "food": ["foodnetwork", "bonappetit"],
    "events": ["LiveNation", "Eventbrite"],
    "trending": ["Reuters", "AP", "BBCBreaking"],
    "local": ["ABC", "CBSNews"],
}

REDDIT_HEADERS = {
    "User-Agent": "TrendTruthHackathon/1.2 (by u/public-trend-app)",
}
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

METADATA_CACHE_TTL_SECONDS = 1800
_metadata_cache_lock = threading.Lock()
_metadata_cache: dict[str, dict[str, Any]] = {}


def get_available_categories() -> list[dict[str, str]]:
    return [{"id": key, "label": CATEGORY_LABELS[key]} for key in CATEGORY_ORDER]


def normalize_category(category: str | None) -> str:
    if not category:
        return "all"
    normalized = category.strip().lower()
    if normalized in CATEGORY_ORDER:
        return normalized
    return "all"


def _safe_get_json(url: str, params: dict[str, Any] | None = None) -> Any | None:
    try:
        response = requests.get(url, params=params, headers=REDDIT_HEADERS, timeout=6)
        response.raise_for_status()
        return response.json()
    except Exception:
        return None


def _safe_get_text(
    url: str,
    params: dict[str, Any] | None = None,
    timeout: int = 12,
    headers: dict[str, str] | None = None,
) -> str:
    try:
        response = requests.get(url, params=params, timeout=timeout, headers=headers)
        response.raise_for_status()
        return response.text
    except Exception:
        return ""


def _parse_pub_date(date_raw: str) -> dt.datetime:
    if not date_raw:
        return dt.datetime.now(dt.timezone.utc)
    try:
        parsed = parsedate_to_datetime(date_raw)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=dt.timezone.utc)
        return parsed
    except Exception:
        return dt.datetime.now(dt.timezone.utc)


def _domain_from_url(url: str) -> str:
    if not url:
        return ""
    try:
        parsed = urllib.parse.urlparse(url)
        return parsed.netloc.lower().replace("www.", "")
    except Exception:
        return ""


def _source_logo_url(url: str) -> str:
    domain = _domain_from_url(url)
    if not domain:
        return ""
    return ""


def _strip_html(raw_html: str) -> str:
    if not raw_html:
        return ""
    text = re.sub(r"<[^>]+>", " ", raw_html)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _compact_text(text: str, max_len: int = 210) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "")).strip()
    if len(cleaned) <= max_len:
        return cleaned
    return cleaned[: max_len - 3].rstrip() + "..."


def _fallback_summary_from_title(title: str) -> str:
    return _compact_text(
        f"{title}. This is a trending story; open the official source for full details.",
        max_len=200,
    )


def _normalize_compare_text(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", (text or "").lower()).strip()


def _summary_is_too_close_to_title(summary: str, title: str) -> bool:
    clean_summary = _normalize_compare_text(summary)
    clean_title = _normalize_compare_text(title)
    if not clean_summary or not clean_title:
        return True
    if clean_summary == clean_title:
        return True
    if clean_summary.startswith(clean_title):
        return True
    title_words = clean_title.split()
    summary_words = clean_summary.split()
    if len(summary_words) <= len(title_words) + 3:
        overlap = set(title_words) & set(summary_words)
        if len(overlap) >= max(3, len(title_words) - 1):
            return True
    return False


def _extract_meta_tag_value(html_text: str, key: str) -> str:
    patterns = [
        rf'<meta[^>]+property=["\']{re.escape(key)}["\'][^>]+content=["\']([^"\']+)["\']',
        rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']{re.escape(key)}["\']',
        rf'<meta[^>]+name=["\']{re.escape(key)}["\'][^>]+content=["\']([^"\']+)["\']',
        rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']{re.escape(key)}["\']',
    ]
    for pattern in patterns:
        match = re.search(pattern, html_text, flags=re.IGNORECASE)
        if match:
            return html.unescape(match.group(1).strip())
    return ""


def _extract_title_tag(html_text: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", html_text, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    return _compact_text(_strip_html(match.group(1)), max_len=180)


def _extract_first_paragraph(html_text: str) -> str:
    for paragraph in re.findall(
        r"<p[^>]*>(.*?)</p>",
        html_text,
        flags=re.IGNORECASE | re.DOTALL,
    )[:30]:
        candidate = _compact_text(_strip_html(paragraph), max_len=240)
        if len(candidate) < 70:
            continue
        lowered = candidate.lower()
        if "javascript" in lowered or "cookie" in lowered or "subscribe" in lowered:
            continue
        return candidate
    return ""


def _base_url_from_link(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


def _is_google_rss_article_url(url: str) -> bool:
    return "news.google.com/rss/articles/" in (url or "")


def _fallback_screenshot_target(url: str, source_url: str = "") -> str:
    if source_url and _is_google_rss_article_url(url):
        return source_url
    return source_url or url


def _thum_url(url: str) -> str:
    if not url:
        return ""
    encoded = urllib.parse.quote(url, safe="")
    return f"https://image.thum.io/get/width/900/noanimate/{encoded}"


def _mshots_url(url: str) -> str:
    if not url:
        return ""
    encoded = urllib.parse.quote(url, safe="")
    return f"https://s.wordpress.com/mshots/v1/{encoded}?w=900"


def _webshot_url(url: str) -> str:
    # Primary screenshot fallback: mshots is currently more reliable than thum.io.
    return _mshots_url(url)


def _looks_like_brand_asset(image_url: str) -> bool:
    if not image_url:
        return False
    lower = image_url.lower()
    logo_markers = (
        "logo",
        "favicon",
        "icon",
        "sprite",
        "avatar",
        "brandmark",
        "masthead",
        "site-logo",
        "header-logo",
        "apple-touch-icon",
        "blank.gif",
        "spacer.gif",
        "pixel",
    )
    if any(marker in lower for marker in logo_markers):
        return True
    if lower.endswith(".svg"):
        return True
    return False


def _read_article_metadata(url: str) -> dict[str, str]:
    if not url:
        return {}

    now = time.time()
    with _metadata_cache_lock:
        cached = _metadata_cache.get(url)
        if cached and (now - float(cached.get("at", 0))) < METADATA_CACHE_TTL_SECONDS:
            return dict(cached.get("meta", {}))

    try:
        response = requests.get(url, timeout=3.5, headers=BROWSER_HEADERS, allow_redirects=True)
        response.raise_for_status()
        html_text = response.text[:300000]
        final_url = response.url or url
    except Exception:
        return {}

    description = _extract_meta_tag_value(html_text, "og:description")
    if not description:
        description = _extract_meta_tag_value(html_text, "twitter:description")
    if not description:
        description = _extract_meta_tag_value(html_text, "description")
    if not description and "news.google.com" not in final_url:
        description = _extract_first_paragraph(html_text)

    image_url = _extract_meta_tag_value(html_text, "og:image")
    if not image_url:
        image_url = _extract_meta_tag_value(html_text, "twitter:image")
    if not image_url and "news.google.com" in final_url:
        google_img = re.search(
            r"https://lh3\\.googleusercontent\\.com/[^\"'\\s>]+",
            html_text,
            flags=re.IGNORECASE,
        )
        if not google_img:
            escaped_img = re.search(
                r"https:\\\\/\\\\/lh3\\.googleusercontent\\.com\\\\/[^\"'\\s>]+",
                html_text,
                flags=re.IGNORECASE,
            )
            if escaped_img:
                unescaped = escaped_img.group(0).replace("\\/", "/")
                google_img = re.search(
                    r"https://lh3\\.googleusercontent\\.com/[^\"'\\s>]+",
                    unescaped,
                    flags=re.IGNORECASE,
                )
        if not google_img:
            unicode_escaped_img = re.search(
                r"https:\\\\u002F\\\\u002Flh3\\.googleusercontent\\.com\\\\u002F[^\"'\\s>]+",
                html_text,
                flags=re.IGNORECASE,
            )
            if unicode_escaped_img:
                unescaped = (
                    unicode_escaped_img.group(0)
                    .replace("\\u002F", "/")
                    .replace("\\/", "/")
                )
                google_img = re.search(
                    r"https://lh3\\.googleusercontent\\.com/[^\"'\\s>]+",
                    unescaped,
                    flags=re.IGNORECASE,
                )
        if google_img:
            image_url = re.sub(r"=w\\d+.*$", "=w1200-h630-p", google_img.group(0))
    if image_url:
        image_url = urllib.parse.urljoin(final_url, image_url)
    if _looks_like_brand_asset(image_url):
        image_url = ""

    site_name = _extract_meta_tag_value(html_text, "og:site_name")
    if not site_name:
        site_name = _domain_from_url(final_url)

    meta = {
        "description": _compact_text(_strip_html(description), max_len=230),
        "image_url": image_url,
        "site_name": _compact_text(site_name, max_len=70),
        "resolved_url": final_url,
        "page_title": _extract_title_tag(html_text),
    }
    with _metadata_cache_lock:
        _metadata_cache[url] = {"at": now, "meta": meta}
    return meta


def _enrich_trend_item(item: TrendItem) -> TrendItem:
    article_meta = _read_article_metadata(item.url)
    if not article_meta:
        fallback_source = item.source_name or _domain_from_url(item.url) or item.platform
        fallback_target = _fallback_screenshot_target(item.url, item.source_url or "")
        fallback_image = item.image_url or _webshot_url(fallback_target) or _thum_url(fallback_target)
        return item.model_copy(
            update={
                "source_name": fallback_source,
                "source_url": item.source_url or _base_url_from_link(item.url),
                "image_url": fallback_image,
            }
        )

    summary = item.summary
    if _summary_is_too_close_to_title(summary, item.title):
        meta_description = article_meta.get("description", "")
        if meta_description and not _summary_is_too_close_to_title(meta_description, item.title):
            summary = meta_description
    if _summary_is_too_close_to_title(summary, item.title):
        summary = _compact_text(
            "Read the full report from the official source for details and context.",
            max_len=180,
        )

    image_url = item.image_url
    if not image_url or "google.com/s2/favicons" in image_url:
        image_url = article_meta.get("image_url", "") or image_url
    if _looks_like_brand_asset(image_url):
        image_url = ""
    if not image_url:
        resolved_url = article_meta.get("resolved_url", item.url)
        fallback_target = _fallback_screenshot_target(resolved_url, item.source_url or "")
        image_url = _webshot_url(fallback_target) or _thum_url(fallback_target)

    source_name = (
        item.source_name
        or article_meta.get("site_name", "")
        or _domain_from_url(item.url)
        or item.platform
    )
    source_url = item.source_url or _base_url_from_link(article_meta.get("resolved_url", item.url))

    return item.model_copy(
        update={
            "summary": summary,
            "image_url": image_url,
            "source_name": source_name,
            "source_url": source_url,
        }
    )


def _infer_category(title: str, fallback: str = "trending") -> str:
    text = title.lower()
    for category, words in CATEGORY_KEYWORDS.items():
        if any(word in text for word in words):
            return category
    return fallback


def _matches_category(title: str, category: str) -> bool:
    if category in ("all", "trending"):
        return True
    words = CATEGORY_KEYWORDS.get(category, set())
    if not words:
        return True
    lower = title.lower()
    return any(word in lower for word in words)


def _normalize_title(title: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", title.lower()).strip()


def _make_gnews_id(category: str, url: str, title: str) -> str:
    raw = f"{category}|{url}|{title}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _engagement_from_recency(created_utc: int, floor: int = 10) -> int:
    hours_old = max(1.0, (time.time() - float(created_utc)) / 3600.0)
    score = max(float(floor), 120.0 / hours_old)
    return int(score)


def fetch_reddit_trends(limit: int, category: str) -> list[TrendItem]:
    subreddit_list = CATEGORY_REDDIT_SUBREDDITS.get(category, DEFAULT_REDDIT_SUBREDDITS)
    if category == "all":
        subreddit_list = DEFAULT_REDDIT_SUBREDDITS
    per_sub = max(3, (limit // max(len(subreddit_list), 1)) + 2)
    trends: list[TrendItem] = []

    for subreddit in subreddit_list:
        payload = _safe_get_json(
            f"https://www.reddit.com/r/{subreddit}/hot.json",
            params={"limit": per_sub},
        )
        if not payload:
            continue
        children = payload.get("data", {}).get("children", [])
        for child in children:
            data = child.get("data", {})
            if data.get("stickied"):
                continue
            title = data.get("title", "").strip()
            if not title:
                continue

            score = int(data.get("score", 0))
            comments = int(data.get("num_comments", 0))
            created_utc = int(data.get("created_utc", int(time.time())))
            permalink = data.get("permalink", "")
            permalink_url = f"https://www.reddit.com{permalink}" if permalink else ""
            external_url = (data.get("url_overridden_by_dest") or data.get("url") or "").strip()
            url = external_url or permalink_url
            summary = _compact_text(data.get("selftext", "") or data.get("title", ""))
            if not summary:
                summary = _fallback_summary_from_title(title)
            thumbnail = data.get("thumbnail", "")
            image_url = ""
            if isinstance(thumbnail, str) and thumbnail.startswith("http"):
                image_url = html.unescape(thumbnail)
            preview = data.get("preview", {})
            if not image_url and isinstance(preview, dict):
                try:
                    src = preview.get("images", [])[0].get("source", {}).get("url", "")
                    if src:
                        image_url = html.unescape(src)
                except Exception:
                    image_url = ""
            if _looks_like_brand_asset(image_url):
                image_url = ""
            if not image_url:
                image_url = ""
            source_name = _domain_from_url(external_url) or f"r/{subreddit}"
            source_url = _base_url_from_link(external_url) if external_url else "https://www.reddit.com"
            hinted_fallback = (
                category
                if category != "all"
                else CATEGORY_HINT_BY_SUBREDDIT.get(subreddit, "trending")
            )
            item_category = _infer_category(title, fallback=hinted_fallback)

            trends.append(
                TrendItem(
                    id=f"reddit:{data.get('id', '')}",
                    platform="Reddit",
                    category=item_category,
                    title=title,
                    summary=summary,
                    image_url=image_url,
                    source_name=source_name,
                    source_url=source_url,
                    url=url,
                    author=data.get("author", "unknown"),
                    created_utc=created_utc,
                    metrics={
                        "score": score,
                        "comments": comments,
                        "engagement": score + (comments * 2),
                        "subreddit": subreddit,
                    },
                )
            )

    return _dedupe_and_rank(trends, limit)


def fetch_hackernews_trends(limit: int, category: str) -> list[TrendItem]:
    trends: list[TrendItem] = []
    ids_payload = _safe_get_json("https://hacker-news.firebaseio.com/v0/topstories.json")
    if not isinstance(ids_payload, list):
        return trends

    for story_id in ids_payload[: limit * 5]:
        item = _safe_get_json(f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json")
        if not item or item.get("type") != "story":
            continue
        title = (item.get("title") or "").strip()
        if not title:
            continue

        score = int(item.get("score", 0))
        comments = int(item.get("descendants", 0))
        created_utc = int(item.get("time", int(time.time())))
        url = item.get("url", f"https://news.ycombinator.com/item?id={story_id}")
        domain = _domain_from_url(url)
        summary = _compact_text(
            f"{title} Community signal from Hacker News. Open the article for full context.",
            max_len=190,
        )
        item_category = _infer_category(title, fallback=category if category != "all" else "trending")
        trends.append(
            TrendItem(
                id=f"hn:{story_id}",
                platform="Hacker News",
                category=item_category,
                title=title,
                summary=summary,
                image_url=_webshot_url(url) or _thum_url(url),
                source_name=domain or "Hacker News",
                source_url=_base_url_from_link(url),
                url=url,
                author=item.get("by", "unknown"),
                created_utc=created_utc,
                metrics={
                    "score": score,
                    "comments": comments,
                    "engagement": score + (comments * 3),
                    "domain": domain,
                },
            )
        )
        if len(trends) >= limit:
            break

    return _dedupe_and_rank(trends, limit)


def fetch_reddit_search_trends(limit: int, query: str, category: str) -> list[TrendItem]:
    search_params = {
        "q": query,
        "sort": "relevance",
        "t": "all",
        "limit": max(12, limit * 3),
        "raw_json": 1,
        "include_over_18": "on",
        "type": "link",
    }
    payload = _safe_get_json(
        "https://www.reddit.com/search.json",
        params=search_params,
    )
    children = payload.get("data", {}).get("children", []) if payload else []
    if not children:
        # Alternate endpoint fallback; helps when the default endpoint is empty/rate limited.
        payload = _safe_get_json(
            "https://www.reddit.com/r/all/search.json",
            params={**search_params, "restrict_sr": "false"},
        )
        children = payload.get("data", {}).get("children", []) if payload else []
    if not children:
        return []

    trends: list[TrendItem] = []
    for child in children:
        data = child.get("data", {})
        title = (data.get("title") or "").strip()
        if not title:
            continue
        score = int(data.get("score", 0))
        comments = int(data.get("num_comments", 0))
        created_utc = int(data.get("created_utc", int(time.time())))
        permalink = data.get("permalink", "")
        permalink_url = f"https://www.reddit.com{permalink}" if permalink else ""
        external_url = (data.get("url_overridden_by_dest") or data.get("url") or "").strip()
        url = external_url or permalink_url
        summary = _compact_text(data.get("selftext", "") or title, max_len=220)
        thumbnail = data.get("thumbnail", "")
        image_url = html.unescape(thumbnail) if isinstance(thumbnail, str) and thumbnail.startswith("http") else ""
        preview = data.get("preview", {})
        if not image_url and isinstance(preview, dict):
            try:
                src = preview.get("images", [])[0].get("source", {}).get("url", "")
                if src:
                    image_url = html.unescape(src)
            except Exception:
                image_url = ""
        if _looks_like_brand_asset(image_url):
            image_url = ""
        item_category = _infer_category(title, fallback=category if category != "all" else "trending")
        subreddit = data.get("subreddit", "")
        trends.append(
            TrendItem(
                id=f"redditq:{data.get('id', '')}",
                platform="Reddit",
                category=item_category,
                title=title,
                summary=summary,
                image_url=image_url,
                source_name=_domain_from_url(external_url) or (f"r/{subreddit}" if subreddit else "reddit.com"),
                source_url=_base_url_from_link(external_url) or "https://www.reddit.com",
                url=url,
                author=data.get("author", "unknown"),
                created_utc=created_utc,
                metrics={
                    "score": score,
                    "comments": comments,
                    "engagement": score + (comments * 2),
                    "subreddit": subreddit,
                    "mode": "query",
                },
            )
        )
        if len(trends) >= limit:
            break
    return _dedupe_and_rank(trends, limit)


def fetch_hackernews_search_trends(limit: int, query: str, category: str) -> list[TrendItem]:
    try:
        response = requests.get(
            "https://hn.algolia.com/api/v1/search",
            params={"query": query, "tags": "story", "hitsPerPage": max(8, limit * 2)},
            timeout=5,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return []

    trends: list[TrendItem] = []
    for hit in payload.get("hits", []):
        title = (hit.get("title") or "").strip()
        if not title:
            continue
        story_id = hit.get("objectID", "")
        url = (hit.get("url") or "").strip() or f"https://news.ycombinator.com/item?id={story_id}"
        created_utc = int(hit.get("created_at_i") or int(time.time()))
        score = int(hit.get("points") or 0)
        comments = int(hit.get("num_comments") or 0)
        item_category = _infer_category(title, fallback=category if category != "all" else "trending")
        trends.append(
            TrendItem(
                id=f"hnq:{story_id}",
                platform="Hacker News",
                category=item_category,
                title=title,
                summary=_compact_text(
                    f"{title} Discovered via Hacker News query results. Open source article for full details.",
                    max_len=220,
                ),
                image_url=_webshot_url(url) or _thum_url(url),
                source_name=_domain_from_url(url) or "news.ycombinator.com",
                source_url=_base_url_from_link(url) or "https://news.ycombinator.com",
                url=url,
                author=hit.get("author", "unknown"),
                created_utc=created_utc,
                metrics={
                    "score": score,
                    "comments": comments,
                    "engagement": score + (comments * 3),
                    "mode": "query",
                },
            )
        )
        if len(trends) >= limit:
            break
    return _dedupe_and_rank(trends, limit)


def _google_rss_search(query: str, max_results: int, gl: str) -> list[dict[str, Any]]:
    hl = "en-US"
    ceid = f"{gl}:en"
    rss_url = (
        "https://news.google.com/rss/search?q="
        f"{urllib.parse.quote(query)}&hl={hl}&gl={gl}&ceid={ceid}"
    )
    xml_text = _safe_get_text(rss_url, timeout=7)
    if not xml_text:
        return []

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    channel = root.find("channel")
    if channel is None:
        return []

    records: list[dict[str, Any]] = []
    for item in channel.findall("item")[:max_results]:
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub_date = _parse_pub_date((item.findtext("pubDate") or "").strip())
        description = (item.findtext("description") or "").strip()
        source_el = item.find("source")
        source_name = ""
        source_url = ""
        if source_el is not None:
            source_name = (source_el.text or "").strip()
            source_url = (source_el.attrib.get("url", "") or "").strip()
        if title and link:
            records.append(
                {
                    "title": title,
                    "url": link,
                    "source": source_name or "Google News",
                    "source_url": source_url,
                    "published": pub_date,
                    "description": description,
                }
            )
    return records


def fetch_google_news_trends(limit: int, category: str) -> list[TrendItem]:
    trends: list[TrendItem] = []
    now = dt.datetime.now(dt.timezone.utc)

    if category == "all":
        buckets = [key for key in CATEGORY_ORDER if key != "all"]
        per_bucket = max(2, (limit // max(len(buckets), 1)) + 1)
        targets = [(cat, CATEGORY_QUERIES[cat]) for cat in buckets]
    else:
        targets = [(category, CATEGORY_QUERIES.get(category, CATEGORY_QUERIES["trending"]))]
        per_bucket = max(4, limit)

    for cat, query in targets:
        gl = "IN" if cat == "india" else "US"
        records = _google_rss_search(query=query, max_results=per_bucket, gl=gl)
        for record in records:
            pub_dt: dt.datetime = record["published"]
            created_utc = int(pub_dt.timestamp())
            recency_engagement = _engagement_from_recency(created_utc, floor=12)
            age_hours = max(1.0, (now - pub_dt).total_seconds() / 3600.0)
            cleaned_summary = _strip_html(record.get("description", ""))
            if cleaned_summary:
                cleaned_summary = re.sub(r"\s+(Google News|Read more)\s*$", "", cleaned_summary).strip()
            if not cleaned_summary:
                cleaned_summary = _fallback_summary_from_title(record["title"])
            source_url = record.get("source_url", "")
            image_target = _fallback_screenshot_target(record["url"], source_url)
            image_url = _webshot_url(image_target) or _thum_url(image_target)
            source_name = record["source"] or _domain_from_url(record["url"]) or "Google News"
            trends.append(
                TrendItem(
                    id=f"gnews:{_make_gnews_id(cat, record['url'], record['title'])}",
                    platform="Google News",
                    category=cat,
                    title=record["title"],
                    summary=_compact_text(cleaned_summary, max_len=220),
                    image_url=image_url,
                    source_name=source_name,
                    source_url=source_url or _base_url_from_link(record["url"]),
                    url=record["url"],
                    author=record["source"],
                    created_utc=created_utc,
                    metrics={
                        "score": recency_engagement,
                        "comments": 0,
                        "engagement": recency_engagement + int(max(0.0, 24.0 - age_hours)),
                        "source": record["source"],
                    },
                )
            )

    return _dedupe_and_rank(trends, limit)


def fetch_google_news_query_trends(limit: int, query: str, category: str) -> list[TrendItem]:
    query = (query or "").strip()
    if not query:
        return []

    gl = "IN" if category == "india" else "US"
    records = _google_rss_search(query=query, max_results=max(8, limit), gl=gl)
    now = dt.datetime.now(dt.timezone.utc)
    trends: list[TrendItem] = []
    for record in records:
        title = record.get("title", "").strip()
        if not title:
            continue
        pub_dt: dt.datetime = record["published"]
        created_utc = int(pub_dt.timestamp())
        recency_engagement = _engagement_from_recency(created_utc, floor=14)
        age_hours = max(1.0, (now - pub_dt).total_seconds() / 3600.0)
        cleaned_summary = _strip_html(record.get("description", ""))
        if cleaned_summary:
            cleaned_summary = re.sub(r"\s+(Google News|Read more)\s*$", "", cleaned_summary).strip()
        if not cleaned_summary:
            cleaned_summary = _fallback_summary_from_title(title)

        source_url = record.get("source_url", "")
        source_name = record.get("source", "") or _domain_from_url(record.get("url", "")) or "Google News"
        image_target = _fallback_screenshot_target(record["url"], source_url)
        item_category = _infer_category(title, fallback=category if category != "all" else "trending")
        trends.append(
            TrendItem(
                id=f"gnewsq:{_make_gnews_id(item_category, record['url'], title)}",
                platform="Google News",
                category=item_category,
                title=title,
                summary=_compact_text(cleaned_summary, max_len=230),
                image_url=_webshot_url(image_target) or _thum_url(image_target),
                source_name=source_name,
                source_url=source_url or _base_url_from_link(record["url"]),
                url=record["url"],
                author=source_name,
                created_utc=created_utc,
                metrics={
                    "score": recency_engagement,
                    "comments": 0,
                    "engagement": recency_engagement + int(max(0.0, 24.0 - age_hours)),
                    "source": source_name,
                    "mode": "query",
                },
            )
        )
    return _dedupe_and_rank(trends, limit)


def fetch_x_api_trends(limit: int, category: str) -> list[TrendItem]:
    bearer = os.getenv("X_BEARER_TOKEN", "").strip()
    if not bearer:
        return []

    query = X_QUERY_BY_CATEGORY.get(category, X_QUERY_BY_CATEGORY["trending"])
    if category == "all":
        query = X_QUERY_BY_CATEGORY["trending"]

    headers = {
        "Authorization": f"Bearer {bearer}",
        "User-Agent": "TrendTruthHackathon/1.2",
    }
    params = {
        "query": query,
        "max_results": min(100, max(10, limit * 2)),
        "tweet.fields": "created_at,public_metrics,author_id",
    }
    try:
        response = requests.get(
            "https://api.twitter.com/2/tweets/search/recent",
            params=params,
            headers=headers,
            timeout=12,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return []

    trends: list[TrendItem] = []
    for tweet in payload.get("data", [])[: limit * 2]:
        text = (tweet.get("text", "") or "").replace("\n", " ").strip()
        if not text:
            continue
        metrics = tweet.get("public_metrics", {})
        likes = int(metrics.get("like_count", 0))
        reposts = int(metrics.get("retweet_count", 0))
        replies = int(metrics.get("reply_count", 0))
        quotes = int(metrics.get("quote_count", 0))
        engagement = likes + (reposts * 2) + (replies * 2) + (quotes * 2)
        created_raw = (tweet.get("created_at") or "").replace("Z", "+00:00")
        try:
            created_utc = int(dt.datetime.fromisoformat(created_raw).timestamp())
        except Exception:
            created_utc = int(time.time())

        item_category = _infer_category(text, fallback=category if category != "all" else "trending")
        trends.append(
            TrendItem(
                id=f"x:{tweet.get('id', '')}",
                platform="X",
                category=item_category,
                title=text,
                summary=_compact_text(text, max_len=210),
                image_url=_webshot_url(f"https://x.com/i/web/status/{tweet.get('id', '')}"),
                source_name="x.com",
                source_url="https://x.com",
                url=f"https://x.com/i/web/status/{tweet.get('id', '')}",
                author=tweet.get("author_id", "unknown"),
                created_utc=created_utc,
                metrics={
                    "score": likes,
                    "comments": replies,
                    "engagement": engagement,
                    "reposts": reposts,
                    "quotes": quotes,
                },
            )
        )
    return _dedupe_and_rank(trends, limit)


def fetch_x_nitter_fallback(limit: int, category: str) -> list[TrendItem]:
    accounts = NITTER_ACCOUNTS_BY_CATEGORY.get(category, NITTER_ACCOUNTS_BY_CATEGORY["trending"])
    if category == "all":
        accounts = NITTER_ACCOUNTS_BY_CATEGORY["trending"] + NITTER_ACCOUNTS_BY_CATEGORY["sports"]
    accounts = accounts[:1]

    trends: list[TrendItem] = []
    started_at = time.time()
    for account in accounts:
        if (time.time() - started_at) > 1.0:
            break
        if len(trends) >= limit:
            break
        for instance in NITTER_INSTANCES[:1]:
            if (time.time() - started_at) > 1.0:
                break
            rss_url = f"{instance}/{account}/rss"
            xml_text = _safe_get_text(rss_url, timeout=1)
            if not xml_text:
                continue
            try:
                root = ET.fromstring(xml_text)
            except ET.ParseError:
                continue

            channel = root.find("channel")
            if channel is None:
                continue

            for item in channel.findall("item")[:2]:
                title = (item.findtext("title") or "").strip()
                link = (item.findtext("link") or "").strip()
                pub_date = _parse_pub_date((item.findtext("pubDate") or "").strip())
                if not title or not link:
                    continue
                clean_title = re.sub(r"^[^:]+:\s*", "", title).strip()
                created_utc = int(pub_date.timestamp())
                engagement = _engagement_from_recency(created_utc, floor=8)
                item_category = _infer_category(clean_title, fallback=category if category != "all" else "trending")
                trends.append(
                    TrendItem(
                        id=f"xrss:{_make_gnews_id(item_category, link, clean_title)}",
                        platform="X",
                        category=item_category,
                        title=clean_title,
                        summary=_compact_text(clean_title, max_len=210),
                        image_url=_webshot_url(link),
                        source_name="x.com",
                        source_url="https://x.com",
                        url=link,
                        author=account,
                        created_utc=created_utc,
                        metrics={
                            "score": engagement,
                            "comments": 0,
                            "engagement": engagement,
                            "mode": "nitter_fallback",
                        },
                    )
                )
                if len(trends) >= limit:
                    break

    return _dedupe_and_rank(trends, limit)


def fetch_x_trends(limit: int, category: str) -> tuple[list[TrendItem], str]:
    bearer = os.getenv("X_BEARER_TOKEN", "").strip()
    if bearer:
        items = fetch_x_api_trends(limit, category)
        return items, ("api_ok" if items else "api_error_or_empty")

    fallback_items = fetch_x_nitter_fallback(limit, category)
    if fallback_items:
        return fallback_items, "fallback_rss"
    return [], "fallback_unavailable_missing_token"


def _dedupe_and_rank(trends: list[TrendItem], limit: int) -> list[TrendItem]:
    unique: dict[str, TrendItem] = {}
    for item in trends:
        key = _normalize_title(item.title)
        if not key:
            continue
        existing = unique.get(key)
        if not existing:
            unique[key] = item
            continue
        current_engagement = int(item.metrics.get("engagement", 0))
        existing_engagement = int(existing.metrics.get("engagement", 0))
        if current_engagement > existing_engagement:
            unique[key] = item

    ranked = sorted(
        unique.values(),
        key=lambda x: (int(x.metrics.get("engagement", 0)), int(x.created_utc)),
        reverse=True,
    )
    return ranked[:limit]


def _enrich_items_concurrent(items: list[TrendItem], max_enrich: int) -> list[TrendItem]:
    if not items:
        return []
    max_enrich = max(0, min(max_enrich, len(items)))
    if max_enrich == 0:
        return items

    enriched: list[TrendItem] = items.copy()
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        future_map = {
            executor.submit(_enrich_trend_item, items[index]): index for index in range(max_enrich)
        }
        for future in concurrent.futures.as_completed(future_map):
            index = future_map[future]
            try:
                enriched[index] = future.result()
            except Exception:
                enriched[index] = items[index]
    return enriched


def _balanced_all_categories(items: list[TrendItem], limit: int) -> list[TrendItem]:
    if not items:
        return []

    by_category: dict[str, list[TrendItem]] = {}
    for item in items:
        by_category.setdefault(item.category, []).append(item)
    for bucket in by_category.values():
        bucket.sort(
            key=lambda x: (int(x.metrics.get("engagement", 0)), int(x.created_utc)),
            reverse=True,
        )

    selected: list[TrendItem] = []
    selected_ids: set[str] = set()

    # First pass: one top result from each requested category.
    for cat in [c for c in CATEGORY_ORDER if c != "all"]:
        bucket = by_category.get(cat, [])
        if not bucket:
            continue
        top = bucket.pop(0)
        selected.append(top)
        selected_ids.add(top.id)
        if len(selected) >= limit:
            return selected

    # Second pass: fill remaining slots by global rank.
    for item in items:
        if item.id in selected_ids:
            continue
        selected.append(item)
        selected_ids.add(item.id)
        if len(selected) >= limit:
            break

    return selected[:limit]


def fetch_trends(
    limit: int = 20,
    category: str = "all",
    query: str = "",
) -> tuple[list[TrendItem], dict[str, str]]:
    normalized_category = normalize_category(category)
    query = (query or "").strip()

    if query:
        google_query_items = fetch_google_news_query_trends(
            limit=max(10, int(limit * 0.55)),
            query=query,
            category=normalized_category,
        )
        reddit_query_items = fetch_reddit_search_trends(
            limit=max(5, int(limit * 0.25)),
            query=query,
            category=normalized_category,
        )
        if not reddit_query_items:
            # Keep social coverage present even when Reddit search endpoint is unreliable.
            reddit_query_items = fetch_reddit_trends(max(3, int(limit * 0.2)), normalized_category)
        hn_query_items = fetch_hackernews_search_trends(
            limit=max(4, int(limit * 0.20)),
            query=query,
            category=normalized_category,
        )
        if not hn_query_items:
            hn_query_items = fetch_hackernews_trends(max(2, int(limit * 0.15)), normalized_category)
        query_items = _dedupe_and_rank(
            google_query_items + reddit_query_items + hn_query_items,
            max(limit * 2, 30),
        )[:limit]
        query_items = _enrich_items_concurrent(query_items, max_enrich=min(12, len(query_items)))
        source_health = {
            "reddit": f"ok:{len(reddit_query_items)}" if reddit_query_items else "empty_query_mode",
            "hacker_news": f"ok:{len(hn_query_items)}" if hn_query_items else "empty_query_mode",
            "google_news": f"ok:{len(google_query_items)}" if google_query_items else "empty_query_mode",
            "x": "skipped_query_mode",
        }
        return query_items, source_health

    if normalized_category == "all":
        reddit_target = max(5, int(limit * 0.32))
        hn_target = max(3, int(limit * 0.20))
        gnews_target = max(5, int(limit * 0.30))
        x_target = max(2, limit - reddit_target - hn_target - gnews_target + 2)
    else:
        reddit_target = max(2, int(limit * 0.15))
        hn_target = 1
        gnews_target = max(10, int(limit * 0.70))
        x_target = 1

    reddit_items = fetch_reddit_trends(reddit_target, normalized_category)
    hn_items = fetch_hackernews_trends(hn_target, normalized_category)
    gnews_items = fetch_google_news_trends(gnews_target, normalized_category)
    x_items, x_status = fetch_x_trends(x_target, normalized_category)

    # If category-specific social feeds are sparse, pull a small fallback batch
    # from global feeds so users still see Reddit/Hacker News coverage.
    if len(reddit_items) < 2:
        fallback_reddit = fetch_reddit_trends(max(4, reddit_target), "all")
        reddit_items = _dedupe_and_rank(reddit_items + fallback_reddit, max(6, reddit_target))
    if len(hn_items) < 1:
        fallback_hn = fetch_hackernews_trends(max(3, hn_target + 1), "all")
        hn_items = _dedupe_and_rank(hn_items + fallback_hn, max(3, hn_target))

    ranked_items = _dedupe_and_rank(reddit_items + hn_items + gnews_items + x_items, max(limit * 2, 30))
    if normalized_category == "all":
        all_items = _balanced_all_categories(ranked_items, limit)
    else:
        all_items = ranked_items[:limit]

    # Enrich only top visible items for speed.
    enriched_items = _enrich_items_concurrent(all_items, max_enrich=min(6, len(all_items)))

    source_health = {
        "reddit": f"ok:{len(reddit_items)}" if reddit_items else "empty_or_rate_limited",
        "hacker_news": f"ok:{len(hn_items)}" if hn_items else "empty",
        "google_news": f"ok:{len(gnews_items)}" if gnews_items else "empty_or_rate_limited",
        "x": x_status,
    }
    return enriched_items, source_health

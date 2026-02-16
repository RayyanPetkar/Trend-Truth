import datetime as dt
import threading
import urllib.parse
import xml.etree.ElementTree as ET

import requests

from app.models import EvidenceArticle, VerificationEvidence

_verify_cache_lock = threading.Lock()
_verify_cache: dict[str, tuple[float, VerificationEvidence]] = {}
VERIFY_CACHE_TTL_SECONDS = 900

CREDIBLE_SOURCE_WEIGHTS = {
    "reuters.com": 1.0,
    "apnews.com": 1.0,
    "bbc.com": 0.95,
    "npr.org": 0.95,
    "pbs.org": 0.92,
    "nytimes.com": 0.9,
    "wsj.com": 0.9,
    "washingtonpost.com": 0.9,
    "bloomberg.com": 0.88,
    "financialtimes.com": 0.88,
    "economist.com": 0.88,
    "theguardian.com": 0.87,
    "usatoday.com": 0.8,
    "abcnews.go.com": 0.82,
    "cnn.com": 0.78,
    "cbsnews.com": 0.8,
    "nbcnews.com": 0.8,
    "aljazeera.com": 0.79,
    "forbes.com": 0.72,
    "techcrunch.com": 0.7,
    "theverge.com": 0.7,
    "thehindu.com": 0.84,
    "indianexpress.com": 0.82,
    "ndtv.com": 0.76,
    "livemint.com": 0.78,
    "hindustantimes.com": 0.76,
    "timesofindia.indiatimes.com": 0.68,
    "firstpost.com": 0.62,
}

SOURCE_NAME_WEIGHTS = {
    "reuters": 1.0,
    "associated press": 1.0,
    "ap news": 1.0,
    "bbc": 0.95,
    "npr": 0.95,
    "pbs": 0.92,
    "new york times": 0.9,
    "wall street journal": 0.9,
    "washington post": 0.9,
    "bloomberg": 0.88,
    "financial times": 0.88,
    "the economist": 0.88,
    "the guardian": 0.87,
    "usa today": 0.8,
    "abc news": 0.82,
    "cnn": 0.78,
    "cbs news": 0.8,
    "nbc news": 0.8,
    "al jazeera": 0.79,
    "forbes": 0.72,
    "techcrunch": 0.7,
    "the verge": 0.7,
    "the hindu": 0.84,
    "indian express": 0.82,
    "ndtv": 0.76,
    "mint": 0.78,
    "hindustan times": 0.76,
    "times of india": 0.68,
}


def _domain_from_url(url: str) -> str:
    if not url:
        return ""
    try:
        parsed = urllib.parse.urlparse(url)
        return parsed.netloc.lower().replace("www.", "")
    except Exception:
        return ""


def _weight_for_domain(domain: str) -> float:
    for candidate, weight in CREDIBLE_SOURCE_WEIGHTS.items():
        if domain.endswith(candidate):
            return weight
    return 0.0


def _weight_for_source_name(source_name: str) -> float:
    normalized = source_name.strip().lower()
    if not normalized:
        return 0.0
    for candidate, weight in SOURCE_NAME_WEIGHTS.items():
        if candidate in normalized:
            return weight
    return 0.0


def estimate_source_trust(source_name: str, source_url: str) -> float:
    domain_weight = _weight_for_domain(_domain_from_url(source_url))
    name_weight = _weight_for_source_name(source_name)
    return max(domain_weight, name_weight)


def _parse_pub_date(pub_date: str) -> dt.datetime:
    if not pub_date:
        return dt.datetime.now(dt.timezone.utc)
    for fmt in ("%a, %d %b %Y %H:%M:%S %Z", "%a, %d %b %Y %H:%M:%S %z"):
        try:
            parsed = dt.datetime.strptime(pub_date, fmt)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=dt.timezone.utc)
            return parsed
        except ValueError:
            continue
    return dt.datetime.now(dt.timezone.utc)


def verify_claim(query: str, max_results: int = 8) -> VerificationEvidence:
    key = f"{query.strip().lower()}:{max_results}"
    with _verify_cache_lock:
        cached = _verify_cache.get(key)
        if cached and (dt.datetime.now().timestamp() - cached[0]) < VERIFY_CACHE_TTL_SECONDS:
            return cached[1]

    rss_url = (
        "https://news.google.com/rss/search?q="
        f"{urllib.parse.quote(query)}&hl=en-US&gl=US&ceid=US:en"
    )

    articles: list[EvidenceArticle] = []
    try:
        response = requests.get(rss_url, timeout=4)
        response.raise_for_status()
        root = ET.fromstring(response.text)
    except Exception:
        result = VerificationEvidence(
            query=query,
            credible_hits=0,
            total_hits=0,
            source_diversity=0,
            confidence=0.0,
            articles=[],
        )
        with _verify_cache_lock:
            _verify_cache[key] = (dt.datetime.now().timestamp(), result)
        return result

    channel = root.find("channel")
    if channel is None:
        result = VerificationEvidence(
            query=query,
            credible_hits=0,
            total_hits=0,
            source_diversity=0,
            confidence=0.0,
            articles=[],
        )
        with _verify_cache_lock:
            _verify_cache[key] = (dt.datetime.now().timestamp(), result)
        return result

    for item in channel.findall("item")[:max_results]:
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub_date = (item.findtext("pubDate") or "").strip()

        source_el = item.find("source")
        source_name = ""
        source_url = ""
        if source_el is not None:
            source_name = (source_el.text or "").strip()
            source_url = (source_el.attrib.get("url", "") or "").strip()

        domain = _domain_from_url(source_url) or _domain_from_url(link)
        source_weight = _weight_for_domain(domain)
        if source_weight == 0.0:
            source_weight = _weight_for_source_name(source_name)
        articles.append(
            EvidenceArticle(
                title=title,
                source=source_name or domain or "Unknown",
                source_url=source_url,
                article_url=link,
                published_at=_parse_pub_date(pub_date).isoformat(),
                source_weight=source_weight,
            )
        )

    credible_hits = sum(1 for article in articles if article.source_weight >= 0.75)
    weighted_sum = sum(article.source_weight for article in articles)
    diversity = len({article.source for article in articles if article.source_weight > 0})
    total_hits = len(articles)

    if total_hits == 0:
        confidence = 0.0
    else:
        # Mix of number of strong sources, weighted trust, and source diversity.
        confidence = min(
            1.0,
            (credible_hits / max(total_hits, 1)) * 0.55
            + (weighted_sum / max(total_hits, 1)) * 0.35
            + (min(diversity, 6) / 6) * 0.10,
        )

    result = VerificationEvidence(
        query=query,
        credible_hits=credible_hits,
        total_hits=total_hits,
        source_diversity=diversity,
        confidence=round(confidence, 4),
        articles=articles[:8],
    )
    with _verify_cache_lock:
        _verify_cache[key] = (dt.datetime.now().timestamp(), result)
    return result

import math
import time

from app.models import AnalysisResult, TrendItem
from app.services.verifier import estimate_source_trust, verify_claim

SENSATIONAL_KEYWORDS = {
    "shocking",
    "must watch",
    "rumor",
    "unverified",
    "leaked",
    "explodes",
    "you won't believe",
    "viral",
    "breaking",
}


def _clamp(value: float, min_val: float = 0.0, max_val: float = 1.0) -> float:
    return max(min_val, min(max_val, value))


def _language_risk(title: str) -> float:
    lower = title.lower()
    keyword_hits = sum(1 for k in SENSATIONAL_KEYWORDS if k in lower)
    exclamation_risk = 0.15 if "!" in title else 0.0
    caps_words = [w for w in title.split() if len(w) > 4 and w.isupper()]
    caps_risk = min(0.2, len(caps_words) * 0.05)
    return _clamp(keyword_hits * 0.08 + exclamation_risk + caps_risk)


def _spread_index(trend: TrendItem) -> float:
    score = float(trend.metrics.get("score", 0))
    comments = float(trend.metrics.get("comments", 0))
    engagement = float(trend.metrics.get("engagement", score + comments))
    hours_old = max(1.0, (time.time() - float(trend.created_utc)) / 3600.0)
    velocity = engagement / hours_old
    # Saturating transform for readability on a 0-100 scale.
    spread = 100.0 * (1 - math.exp(-velocity / 120.0))
    return round(_clamp(spread / 100.0) * 100, 2)


def analyze_trend(trend: TrendItem) -> AnalysisResult:
    evidence = verify_claim(trend.title)
    language_risk = _language_risk(trend.title)
    verification_strength = evidence.confidence
    spread_index = _spread_index(trend)
    source_trust = estimate_source_trust(trend.source_name, trend.source_url or trend.url)

    weak_evidence_penalty = 0.10 * (1.0 - min(evidence.total_hits, 10) / 10.0)
    low_diversity_penalty = 0.06 if evidence.source_diversity <= 1 else 0.0
    corroboration_bonus = min(evidence.credible_hits, 5) * 0.05
    platform_adjust = {
        "Google News": -0.16,
        "Hacker News": -0.06,
        "Reddit": 0.06,
        "X": 0.10,
    }.get(trend.platform, 0.0)

    fake_probability = _clamp(
        0.40
        - (verification_strength * 0.72)
        - corroboration_bonus
        - (source_trust * 0.20)
        + platform_adjust
        + (language_risk * 0.20)
        + weak_evidence_penalty
        + low_diversity_penalty
    )
    if source_trust >= 0.75 and evidence.credible_hits >= 1:
        fake_probability = _clamp(fake_probability - 0.10)
    if source_trust >= 0.85 and evidence.confidence >= 0.45:
        fake_probability = _clamp(fake_probability - 0.08)

    credibility_score = _clamp(1.0 - fake_probability)

    reasons: list[str] = []
    if evidence.credible_hits >= 3:
        reasons.append("Multiple high-trust outlets reported related claims.")
    elif evidence.credible_hits == 0:
        reasons.append("Strong corroboration was limited in current checks.")
    else:
        reasons.append("Partial corroboration from trusted outlets was found.")

    if evidence.source_diversity <= 1:
        reasons.append("Low source diversity increases uncertainty.")
    if language_risk >= 0.2:
        reasons.append("Headline wording appears potentially sensational.")
    if spread_index >= 70:
        reasons.append("High social velocity suggests rapid spread.")
    if source_trust >= 0.8:
        reasons.append("Source has a strong historical trust profile.")
    reasons.append("Assessment is probabilistic and may update with new evidence.")

    if fake_probability <= 0.30:
        verdict = "Low Risk"
    elif fake_probability <= 0.60:
        verdict = "Medium Risk"
    else:
        verdict = "High Risk"

    return AnalysisResult(
        trend=trend,
        fake_probability=round(fake_probability * 100, 2),
        spread_index=spread_index,
        credibility_score=round(credibility_score * 100, 2),
        verdict=verdict,
        reasons=reasons,
        evidence=evidence,
    )

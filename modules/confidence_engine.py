SEVERITY_SCORE = {
    "very_low": 10,
    "low": 25,
    "medium": 50,
    "high": 75,
    "very_high": 100,
}

DEFAULT_BOUNDARIES = {
    "sangat_rendah_max": 24,
    "rendah_max": 44,
    "sedang_max": 64,
    "tinggi_max": 84,
}


def clamp_score(score):
    return max(0.0, min(100.0, float(score or 0)))


def confidence_label(score, boundaries=None):
    b = boundaries or DEFAULT_BOUNDARIES
    score = clamp_score(score)
    if score <= float(b.get("sangat_rendah_max", 24)):
        return "Sangat rendah"
    if score <= float(b.get("rendah_max", 44)):
        return "Rendah"
    if score <= float(b.get("sedang_max", 64)):
        return "Sedang"
    if score <= float(b.get("tinggi_max", 84)):
        return "Tinggi"
    return "Sangat tinggi"


def calculate_confidence(
    exact_or_synonym_score=0,
    fuzzy_score=0,
    semantic_score=0,
    severity="medium",
    feedback_adjustment=0,
    allowable_score=0,
    exception_penalty=0,
    weights=None,
):
    weights = weights or {}
    severity_score = SEVERITY_SCORE.get(str(severity or "medium"), 50)
    score = (
        float(weights.get("exact_weight", 0.25)) * exact_or_synonym_score
        + float(weights.get("fuzzy_weight", 0.20)) * fuzzy_score
        + float(weights.get("semantic_weight", 0.30)) * semantic_score
        + float(weights.get("severity_weight", 0.10)) * severity_score
        + float(weights.get("feedback_weight", 0.10)) * feedback_adjustment
        - float(weights.get("allowable_penalty_weight", 0.20)) * allowable_score
        - float(exception_penalty or 0)
    )
    return clamp_score(score)

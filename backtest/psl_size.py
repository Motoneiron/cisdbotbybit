"""Frozen P(SL) overlay for Lever-1 quality sizing.

Runtime has no sklearn dependency: the exported scaler/logit parameters live in
``psl_size_model.json``.  On any malformed input/model error the caller should
keep the raw QSZ multiplier.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Mapping


MODEL_PATH = Path(__file__).with_name("psl_size_model.json")


def load_model(path: Path = MODEL_PATH) -> dict:
    model = json.loads(path.read_text(encoding="utf-8"))
    n = len(model["features"])
    for key in ("medians", "scaler_mean", "scaler_scale", "coef"):
        if len(model[key]) != n:
            raise ValueError(f"PSL model {key}: expected {n}, got {len(model[key])}")
    if len(model["p_edges"]) != 5 or len(model["quartile_adjustments"]) != 4:
        raise ValueError("PSL model must contain four probability buckets")
    return model


MODEL = load_model()


def _finite(value: Any, fallback: float) -> float:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return float(fallback)
    return x if math.isfinite(x) else float(fallback)


def build_features(raw: Mapping[str, Any]) -> dict[str, float]:
    """Build the exact causal feature vector used by the research model."""
    start_n = _finite(raw.get("start_n"), 0.0)
    bars1 = _finite(raw.get("bars1"), 0.0)
    touches = _finite(raw.get("prior_touches"), 0.0)
    never = float(bool(raw.get("never")))
    short_start = float(start_n <= 2.0)
    d_strong = float(touches >= 7.0)
    weak_touches = float(touches < 6.0)
    return {
        "sw_atr": raw.get("sw_atr"),
        "prior_touches": raw.get("prior_touches"),
        "never": never,
        "short_start": short_start,
        "start_n": start_n,
        "start_range_atr": raw.get("start_range_atr"),
        "bars1": bars1,
        "unreclaim": float(bool(raw.get("unreclaim"))),
        "no_start_fvg": float(bool(raw.get("no_start_fvg"))),
        "no_conf_fvg": float(bool(raw.get("no_conf_fvg"))),
        "vol_ratio": raw.get("vol_ratio"),
        "d_strong": d_strong,
        "never_x_slow": never * float(bars1 > 4.0),
        "short_x_never": short_start * never,
        "never_x_d": never * d_strong,
        "never_x_weak": never * weak_touches,
    }


def predict_sl_probability(raw: Mapping[str, Any], model: dict = MODEL) -> float:
    features = build_features(raw)
    z = float(model["intercept"])
    for i, name in enumerate(model["features"]):
        value = _finite(features.get(name), model["medians"][i])
        scale = _finite(model["scaler_scale"][i], 1.0)
        if scale <= 0:
            scale = 1.0
        standardized = (value - float(model["scaler_mean"][i])) / scale
        z += standardized * float(model["coef"][i])
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    ez = math.exp(z)
    return ez / (1.0 + ez)


def apply_psl_sizing(
    raw_qsz: float,
    raw_features: Mapping[str, Any],
    model: dict = MODEL,
) -> dict[str, Any]:
    """Apply mild P(SL)-quartile overlay and production envelope."""
    qsz = _finite(raw_qsz, 1.0)
    p_sl = predict_sl_probability(raw_features, model)
    finite_edges = [float(x) for x in model["p_edges"][1:-1]]
    bucket = sum(p_sl > edge for edge in finite_edges)
    adjustment = float(model["quartile_adjustments"][bucket])
    mult = qsz * adjustment * float(model["risk_scale"])
    mult = min(float(model["max_mult"]), max(float(model["min_mult"]), mult))
    return {
        "psl_probability": round(p_sl, 6),
        "psl_quartile": int(bucket + 1),
        "psl_adjustment": adjustment,
        "psl_size_mult": round(mult, 4),
        "psl_model_version": str(model["version"]),
    }

# -*- coding: utf-8 -*-
"""HTF Context Engine — карта пути и признаки препятствий (ТЗ §9–§12).

Для LONG берутся объекты ВЫШЕ entry, для SHORT — НИЖЕ. Дистанция считается до
ближайшей границы объекта (для FVG — lo сверху / hi снизу; для свинга и уровней — level).

Правила состояний (см. htf_state):
  * FILLED FVG — не препятствие (объект пройден);
  * SWEPT/BROKEN свинг — не препятствие (уровень уже снят/пробит, ТЗ §5);
  * PARTIALLY_FILLED FVG — препятствие; дистанция до ближайшей границы зоны.

Признаки — исследовательские, НЕ фильтры (ТЗ §16). Порогов не подбирать.
"""
from __future__ import annotations

from .htf_objects import HTFObject
from .htf_state import TFTracker

#: Максимальная дистанция объекта в R, попадающего в карту пути (в пунктах дальше нет смысла).
MAX_PATH_R = 5.0

_REF_TF = {"PDH": "1D", "PDL": "1D", "PWH": "1W", "PWL": "1W"}


def _is_dead(o: HTFObject, st: dict) -> bool:
    if o.is_fvg():
        return st["state"] == "FILLED"
    return st["state"] in ("SWEPT", "BROKEN")


def fvg_remaining(o: HTFObject, st: dict) -> tuple[float, float]:
    """Незаполненная (остаточная) часть FVG-зоны по состоянию на момент t.

    FVG_BULL заполняется сверху вниз: остаток = [lo, min_low_since].
    FVG_BEAR заполняется снизу вверх: остаток = [max_high_since, hi].
    """
    d = float(st["fill_pct"] or 0.0) * (float(o.hi) - float(o.lo))
    if o.kind == "FVG_BULL":
        return float(o.lo), float(o.lo) + (float(o.hi) - float(o.lo)) - d
    return float(o.lo) + d, float(o.hi)


def _obj_side_dist(o: HTFObject, st: dict, entry: float, direction: str) -> tuple[str, float] | None:
    """Сторона и дистанция объекта относительно entry для направления сделки.

    Для FVG дистанция считается до ближайшей границы ОСТАТОЧНОЙ (незаполненной) части;
    если остаток целиком «за спиной» — объект не препятствие; если остаток накрывает
    entry — "straddle" (0.0). Возвращает ("above"|"below"|"straddle", dist) или None.
    """
    if o.is_fvg():
        r_lo, r_hi = fvg_remaining(o, st)
        if direction == "LONG":
            if r_lo >= entry:
                return ("above", r_lo - entry)
            if r_hi <= entry:
                return None
            return ("straddle", 0.0)
        if r_hi <= entry:
            return ("below", entry - r_hi)
        if r_lo >= entry:
            return None
        return ("straddle", 0.0)
    # swing
    if direction == "LONG":
        if o.kind == "SWING_HIGH" and float(o.level) > entry:
            return ("above", float(o.level) - entry)
        return None
    if o.kind == "SWING_LOW" and float(o.level) < entry:
        return ("below", entry - float(o.level))
    return None


def collect_obstacles(
    trackers: dict[str, TFTracker],
    k_by_tf: dict[str, int],
    entry: float,
    direction: str,
    risk: float,
    refs_dist: dict,
    exclusion=None,
) -> list[dict]:
    """Все актуальные препятствия по направлению сделки (дистанция <= MAX_PATH_R).

    exclusion — объект с методом disabled(o: HTFObject) -> bool (исключение source-уровня, ТЗ §6).
    """
    out: list[dict] = []
    for tf in ("4H", "1D", "1W"):
        tr = trackers.get(tf)
        if tr is None:
            continue
        k = k_by_tf.get(tf, -1)
        if k < 0:
            continue
        for i, o in tr.available(k):
            if exclusion is not None and exclusion.disabled(o):
                continue
            st = tr.obj_state(i)
            if _is_dead(o, st):
                continue
            sd = _obj_side_dist(o, st, entry, direction)
            if sd is None:
                continue
            side, dist = sd
            dist_r = dist / risk if risk else float("inf")
            if dist_r > MAX_PATH_R:
                continue
            rec = {
                "tf": tf,
                "type": o.kind,
                "state": st["state"],
                "side": side,
                "direction": direction,
                "created_at": str(o.created_at),
                "available_at": str(o.available_at),
                "distance_pct": round(dist / entry * 100.0, 4),
                "distance_R": round(dist_r, 4),
            }
            if o.is_fvg():
                r_lo, r_hi = fvg_remaining(o, st)
                rec["lo"] = round(float(o.lo), 10)
                rec["hi"] = round(float(o.hi), 10)
                rec["rem_lo"] = round(r_lo, 10)
                rec["rem_hi"] = round(r_hi, 10)
                rec["fill_pct"] = st["fill_pct"]
            else:
                rec["level"] = round(float(o.level), 10)
            out.append(rec)
    # референс-уровни (PDH/PWH для LONG, PDL/PWL для SHORT)
    for name in ("PDH", "PDL", "PWH", "PWL"):
        item = refs_dist.get(name)
        if item is None:
            continue
        want = "above" if direction == "LONG" else "below"
        if item["side"] != want:
            continue
        dist = abs(float(item["distance_abs"]))
        dist_r = dist / risk if risk else float("inf")
        if dist_r > MAX_PATH_R:
            continue
        out.append({
            "tf": _REF_TF[name],
            "type": name,
            "state": "REF",
            "side": want,
            "direction": direction,
            "level": float(item["level"]),
            "ref_bar": item["bar"],
            "distance_pct": round(dist / entry * 100.0, 4),
            "distance_R": round(dist_r, 4),
        })
    out.sort(key=lambda r: r["distance_R"])
    return out


def summarize_features(obstacles: list[dict], tp_r: float = 1.0) -> dict:
    """Сводка признаков по карте пути (ТЗ §10, §11)."""

    def _min_r(pred) -> float | None:
        vals = [o["distance_R"] for o in obstacles if pred(o)]
        return min(vals) if vals else None

    fvg = lambda o: o["type"].startswith("FVG")
    swing = lambda o: o["type"].startswith("SWING")
    ref = lambda o: o["type"] in ("PDH", "PDL", "PWH", "PWL")

    nearest = _min_r(lambda o: True)
    d = [o["distance_R"] for o in obstacles]
    counts = {
        "obstacle_count_0_0.5R": sum(1 for x in d if x < 0.5),
        "obstacle_count_0.5_1R": sum(1 for x in d if 0.5 <= x < 1.0),
        "obstacle_count_1_2R": sum(1 for x in d if 1.0 <= x < 2.0),
        "obstacle_count_2_3R": sum(1 for x in d if 2.0 <= x < 3.0),
        "obstacle_count_under_1R": sum(1 for x in d if x < 1.0),
        "obstacle_count_under_2R": sum(1 for x in d if x < 2.0),
    }
    per_tf: dict = {}
    for tf in ("4H", "1D", "1W"):
        per_tf[f"nearest_{tf.lower()}_obstacle_R"] = _min_r(lambda o, tf=tf: o["tf"] == tf)
    per_tf_cls: dict = {}
    for tf in ("4H", "1D", "1W"):
        per_tf_cls[f"nearest_{tf.lower()}_fvg_R"] = _min_r(lambda o, tf=tf: o["tf"] == tf and fvg(o))
        per_tf_cls[f"nearest_{tf.lower()}_swing_R"] = _min_r(lambda o, tf=tf: o["tf"] == tf and swing(o))

    nearest_pct = obstacles[0]["distance_pct"] if obstacles else None
    summary = {
        "nearest_opposing_obstacle_R": nearest,
        "nearest_opposing_obstacle_pct": nearest_pct,
        "nearest_internal_liquidity_R": _min_r(fvg),
        "nearest_external_liquidity_R": _min_r(lambda o: swing(o) or ref(o)),
        "tp_r": tp_r,
        "tp_blocked": (nearest is not None and nearest < tp_r),
    }
    summary.update(counts)
    summary.update(per_tf)
    summary.update(per_tf_cls)
    return summary


def path_public(obstacles: list[dict]) -> list[dict]:
    """Публичный вид path: отсортированный список препятствий (уже округлён)."""
    return obstacles

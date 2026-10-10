# -*- coding: utf-8 -*-
"""HTF Context Engine — обязательные sanity-тесты (ТЗ §15).

Тесты 1-5: синтетика (FVG/swing availability, fill-статусы, future contamination,
незавершённая HTF-свеча) + проверка «truncation invariance» (контекст на полном
датасете обязан совпадать с контекстом на датасете, обрезанном по close <= t)
и (опционально) реальные данные SOL.

Запуск:  python -m HTF_CONTEXT.htf_validate [--out RUNS/cache/htf_context_validation.json]
"""
from __future__ import annotations

import argparse
import json
import sys
import os

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from HTF_CONTEXT.htf_context import HTFContextEngine
from HTF_CONTEXT.htf_resample import TF_MINUTES


# ----------------------------------------------------------------------------- helpers
def mk_frame(rows: list[tuple]) -> pd.DataFrame:
    """rows: (ts, open, high, low, close) → фрейм с float-колонками."""
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close"])
    df["ts"] = pd.to_datetime(df["ts"])
    df = df.set_index("ts")
    df["volume"] = 1.0
    return df[["open", "high", "low", "close", "volume"]].astype(float)


def synthetic_frame() -> pd.DataFrame:
    """Синтетический 4H-фрейм с известной геометрией (см. комментарии)."""
    return mk_frame([
        ("2024-01-01 00:00", 99.0, 100.0, 98.0, 99.5),
        ("2024-01-01 04:00", 99.5, 101.0, 99.0, 100.0),
        # FVG_A (bull) [100.0, 100.5]: low[2]=100.5 > high[0]=100.0, доступен после close(08:00)=12:00
        ("2024-01-01 08:00", 100.0, 101.5, 100.5, 101.0),
        ("2024-01-01 12:00", 101.0, 102.0, 101.0, 101.5),
        ("2024-01-01 16:00", 101.5, 102.5, 101.2, 102.0),
        ("2024-01-01 20:00", 102.0, 102.8, 101.8, 102.5),
        # SWING_HIGH 105 (i6), известен после close(i7)=01-02 08:00
        ("2024-01-02 00:00", 102.5, 105.0, 102.2, 104.5),
        ("2024-01-02 04:00", 104.5, 104.8, 103.0, 103.5),
        # FVG_B (bull) [102.8, 103.0]: low[8]=102.5 > high[6]=105.0? нет; FVG_B создан на i=7? пересчитано ниже
        ("2024-01-02 08:00", 103.5, 104.0, 102.5, 103.0),
        # касание FVG_A: low=100.2 → частичное заполнение 0.6
        ("2024-01-02 12:00", 103.0, 103.5, 100.2, 102.0),
        # полное заполнение FVG_A: low=99.9 <= 100.0
        ("2024-01-02 16:00", 102.0, 102.5, 99.9, 100.5),
        ("2024-01-02 20:00", 100.5, 101.0, 100.0, 100.8),
        ("2024-01-03 00:00", 100.8, 101.5, 100.5, 101.0),
        ("2024-01-03 04:00", 101.0, 101.8, 100.9, 101.5),
        ("2024-01-03 08:00", 101.5, 102.2, 101.3, 102.0),
        ("2024-01-03 12:00", 102.0, 102.5, 101.8, 102.3),
        # SPIKE-бар (i16): huge high 999.0, доступен только после close = 20:00
        ("2024-01-03 16:00", 102.3, 999.0, 102.0, 102.5),
        ("2024-01-03 20:00", 102.5, 102.6, 102.2, 102.4),
    ])


def find_obj(snapshot: list[dict], kind: str, level: float | None = None,
             lo: float | None = None, tol: float = 1e-9) -> dict | None:
    for rec in snapshot:
        if rec["kind"] != kind:
            continue
        if level is not None and abs((rec.get("level") or 0) - level) <= tol:
            return rec
        if lo is not None and abs((rec.get("lo") or 0) - lo) <= tol:
            return rec
    return None


def sig(entry: float, stop: float, direction: str = "LONG", tp: float = None, sweep: float = None) -> dict:
    return {"direction": direction, "entry": entry, "stop": stop,
            "tp": tp if tp is not None else entry + abs(entry - stop),
            "htf_sweep_level": sweep}


class Result:
    def __init__(self, name: str):
        self.name = name
        self.passed = True
        self.details: list[str] = []

    def check(self, cond: bool, msg: str):
        if not cond:
            self.passed = False
            self.details.append("FAIL: " + msg)
        return cond

    def info(self, msg: str):
        self.details.append(msg)

    def to_dict(self) -> dict:
        return {"test": self.name, "passed": bool(self.passed), "details": self.details}


# ------------------------------------------------------------------------------- tests
def test1_fvg_availability(frame: pd.DataFrame) -> Result:
    r = Result("test1_fvg_availability")
    eng = HTFContextEngine("SYN", {"4H": frame})
    snap_before = eng.objects_snapshot("2024-01-01 11:00")
    r.check(find_obj(snap_before, "FVG_BULL", lo=100.0) is None,
            "FVG не должен существовать до закрытия третьей свечи (11:00)")
    snap_after = eng.objects_snapshot("2024-01-01 12:05")
    obj = find_obj(snap_after, "FVG_BULL", lo=100.0)
    r.check(obj is not None, "FVG должен существовать после close третьей свечи (12:05)")
    if obj:
        r.check(obj["available_at"] == "2024-01-01 12:00:00",
                f"available_at == 12:00, факт: {obj['available_at']}")
        r.check(obj["hi"] == 100.5, f"zone hi == 100.5, факт: {obj['hi']}")
        r.check(obj["state"] == "ACTIVE", f"state ACTIVE, факт: {obj['state']}")
    return r


def test2_swing_availability(frame: pd.DataFrame) -> Result:
    r = Result("test2_swing_availability")
    eng = HTFContextEngine("SYN", {"4H": frame})
    snap_before = eng.objects_snapshot("2024-01-02 07:00")
    r.check(find_obj(snap_before, "SWING_HIGH", level=105.0) is None,
            "swing high не должен существовать до закрытия правой свечи (07:00)")
    snap_after = eng.objects_snapshot("2024-01-02 08:05")
    obj = find_obj(snap_after, "SWING_HIGH", level=105.0)
    r.check(obj is not None, "swing high должен существовать после close правой свечи (08:05)")
    if obj:
        r.check(obj["available_at"] == "2024-01-02 08:00:00",
                f"available_at == 08:00, факт: {obj['available_at']}")
    return r


def test3_fill_states(frame: pd.DataFrame) -> Result:
    r = Result("test3_fill")
    eng = HTFContextEngine("SYN", {"4H": frame})
    s1 = find_obj(eng.objects_snapshot("2024-01-02 15:00"), "FVG_BULL", lo=100.0)
    r.check(s1 is not None and s1["state"] == "ACTIVE", f"до касания ACTIVE, факт: {s1 and s1['state']}")
    s2 = find_obj(eng.objects_snapshot("2024-01-02 16:05"), "FVG_BULL", lo=100.0)
    r.check(s2 is not None and s2["state"] == "PARTIALLY_FILLED",
            f"после касания PARTIALLY_FILLED, факт: {s2 and s2['state']}")
    if s2:
        r.check(abs(float(s2["fill_pct"]) - 0.6) < 1e-9,
                f"fill_pct == 0.6, факт: {s2['fill_pct']}")
    s3 = find_obj(eng.objects_snapshot("2024-01-02 20:05"), "FVG_BULL", lo=100.0)
    r.check(s3 is not None and s3["state"] == "FILLED", f"после полного заполнения FILLED, факт: {s3 and s3['state']}")
    return r


def test4_future_contamination(frame: pd.DataFrame) -> Result:
    r = Result("test4_future_contamination")
    eng = HTFContextEngine("SYN", {"4H": frame})
    s = sig(entry=100.6, stop=99.0)
    ctx1 = eng.context("2024-01-01 11:00", s)
    r.check(len(ctx1["path"]) == 0, f"в 11:00 путь пуст (нет известных объектов), факт: {ctx1['path']}")
    r.check(ctx1["htf"]["4H"]["fvg_above"] == [] and ctx1["htf"]["4H"]["fvg_below"] == [],
            "в 11:00 карта без FVG (все объекты ещё будущие)")
    r.check(all(o["available_at"] <= "2024-01-01 11:00" for o in ctx1["path"]),
            "все объекты ctx1 доступны до t")
    ctx2 = eng.context("2024-01-02 15:00", s)
    types2 = [o["type"] for o in ctx2["path"]]
    # FVG_A [100.0,100.5] ниже entry (не препятствие LONG) и ещё ACTIVE;
    # FVG_B [102.8,103.0] был создан i=7 и ПОЛНОСТЬЮ заполнен баром i=8 (low 102.5 <= 102.8) — мёртв.
    r.check("FVG_BULL" not in types2 and "FVG_BEAR" not in types2,
            f"FVG-объекты не должны быть препятствиями LONG на 15:00 (FVG_A ниже, FVG_B заполнен), факт: {ctx2['path']}")
    r.check(any(o["type"] == "SWING_HIGH" and abs(o["level"] - 105.0) < 1e-9 for o in ctx2["path"]),
            "swing high 105 должен быть препятствием LONG в 15:00 01-02")
    # карта (не фильтрованная по направлению): FVG_A должен быть виден как объект ниже entry
    below = ctx2["htf"]["4H"]["fvg_below"]
    r.check(any(abs(item["lo"] - 100.0) < 1e-9 for item in below),
            f"FVG_A должен быть в fvg_below карты, факт: {below}")
    r.info(f"path@15:00 = {[(o['type'], o.get('level'), o.get('lo'), o['distance_R']) for o in ctx2['path']]}")
    return r


def test5_incomplete_candle(frame: pd.DataFrame) -> Result:
    r = Result("test5_incomplete_htf_candle")
    eng = HTFContextEngine("SYN", {"4H": frame})
    t = "2024-01-03 17:00"  # внутри spike-бара i16 (16:00..20:00)
    s = sig(entry=102.0, stop=100.5)
    ctx_full = eng.context(t, s)
    # обрезаем данные по последний ЗАКРЫТЫЙ бар (close <= t)
    k = 15
    frames_trunc = {"4H": frame.iloc[: k + 1].copy()}
    eng2 = HTFContextEngine("SYN", frames_trunc)
    ctx_trunc = eng2.context(t, s)
    r.check(json.dumps(ctx_full, sort_keys=True) == json.dumps(ctx_trunc, sort_keys=True),
            "контекст на полном датасете совпадает с контекстом на обрезанном (нет загляда)")
    snap = eng.objects_snapshot(t)
    r.check(find_obj(snap, "SWING_HIGH", level=999.0) is None,
            "swing 999 из незавершённого бара не должен быть виден")
    r.check("999" not in json.dumps(ctx_full), "значение 999 не встречается в контексте")
    return r


def test_truncation_invariance(frame: pd.DataFrame) -> Result:
    """Контекст на полном датасете == контекст на датасете, обрезанном по close<=t (несколько t)."""
    r = Result("test_truncation_invariance")
    eng = HTFContextEngine("SYN", {"4H": frame})
    s = sig(entry=102.0, stop=100.5)
    for t, k in (("2024-01-02 15:00", 8), ("2024-01-03 11:00", 14), ("2024-01-03 17:00", 15)):
        c_full = eng.context(t, s)
        eng2 = HTFContextEngine("SYN", {"4H": frame.iloc[: k + 1].copy()})
        c_tr = eng2.context(t, s)
        eq = json.dumps(c_full, sort_keys=True) == json.dumps(c_tr, sort_keys=True)
        r.check(eq, f"t={t}: полный контекст != обрезанный")
    return r


def real_data_check(since: str = "2024-06-01", until: str = "2024-08-01") -> Result:
    """Реальные данные SOL: truncation invariance на настоящих 4H/1D/1W."""
    r = Result("real_data_truncation_SOL")
    path = r"D:\databtcusdt\SOLUSDT-1m\SOLUSDT_1m_full_hdr.csv"
    if not os.path.exists(path):
        r.info("SKIP: файл SOL 1m не найден")
        return r
    from HTF_CONTEXT.htf_resample import (
        bar_close_ns, last_closed_index, load_1m, make_frames, TF_MINUTES,
    )
    # с преисторией для структур
    df1 = load_1m(path, "2023-12-01", until)
    frames = make_frames(df1)
    eng = HTFContextEngine("SOL", frames)
    close_ns = {tf: bar_close_ns(df, tf) for tf, df in frames.items()}
    times = ["2024-06-03 19:15", "2024-06-20 13:30", "2024-07-10 08:45"]
    for t in times:
        ks = {tf: last_closed_index(close_ns[tf], t) for tf in frames}
        entry = float(frames["4H"]["close"].iloc[ks["4H"]]) if ks["4H"] >= 0 else 100.0
        s = sig(entry=entry, stop=entry * 0.985)
        c_full = eng.context(t, s)
        eng2 = HTFContextEngine("SOL", {tf: frames[tf].iloc[: ks[tf] + 1].copy() for tf in frames})
        c_tr = eng2.context(t, s)
        eq = json.dumps(c_full, sort_keys=True) == json.dumps(c_tr, sort_keys=True)
        r.check(eq, f"t={t}: реальные данные SOL — полный контекст != обрезанный")
    r.info("инвариантность на реальных SOL 4H/1D/1W проверена" if r.passed else "")
    return r


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=r"D:\PYTHON\cisdbotbybit\RUNS\cache\htf_context_validation.json")
    args = ap.parse_args()

    frame = synthetic_frame()
    results = [
        test1_fvg_availability(frame),
        test2_swing_availability(frame),
        test3_fill_states(frame),
        test4_future_contamination(frame),
        test5_incomplete_candle(frame),
        test_truncation_invariance(frame),
        real_data_check(),
    ]
    payload = {
        "generated_at": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
        "tests": [x.to_dict() for x in results],
        "all_passed": all(x.passed for x in results),
    }
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    for x in results:
        print(("PASS " if x.passed else "FAIL ") + x.name)
        for d in x.details:
            if d.startswith("FAIL"):
                print("   " + d)
    print("ALL:", "PASS" if payload["all_passed"] else "FAIL", "->", args.out)
    return 0 if payload["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

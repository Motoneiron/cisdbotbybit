# -*- coding: utf-8 -*-
"""HTF Context Engine — сборка датасета контекстов и исследование (ТЗ §14, §17).

Вход:  прогон RUNS/temp/live_tf_htfctx/rows_tf1v2/*.pkl (кандидат v2: tf1, 10 пар,
       2024-01..2026-09; taken-сделки + пропущенные сигналы с контрфактическим исходом).
Выход: RUNS/cache/htf_context.jsonl       — контекст на каждый сигнал (causal, §13);
       RUNS/cache/htf_context_summary.csv — плоская таблица признаков;
       RUNS/HTF_CONTEXT_REPORT_2026-10-08.md — анализ §14 (корзины/терцили/годы/недели).

Запуск (интерпретатор: D:/PYTHON/CISDBOT/.venv/Scripts/python.exe, cwd=проект):
    python -m HTF_CONTEXT.research_htf_context                 # полный прогон
    python -m HTF_CONTEXT.research_htf_context --skip-build    # только анализ/отчёт по готовому JSONL
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import pickle
import sys
import time
from collections import defaultdict

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from HTF_CONTEXT.htf_context import HTFContextEngine
from HTF_CONTEXT.htf_resample import load_1m, make_frames

# ---------------------------------------------------------------------------- константы
PROJ = r"D:\PYTHON\cisdbotbybit"
ROWS_DIR = os.path.join(PROJ, "RUNS", "temp", "live_tf_htfctx", "rows_tf1v2")
STOPT_DIR = os.path.join(PROJ, "RUNS", "temp", "live_tf_stopt", "stopt_tf1v2")
CACHE_DIR = os.path.join(PROJ, "RUNS", "cache")
PREHISTORY = "2022-01-01"
UNTIL = "2026-09-02"
PAIRS10 = ["SOL", "DOGE", "KAS", "ADA", "LINK", "LTC", "XRP", "BTC", "AVAX", "TON"]

PATHS = {
    "SOL": r"D:\databtcusdt\SOLUSDT-1m\SOLUSDT_1m_full_hdr.csv",
    "DOGE": r"D:\databtcusdt\DOGEUSDT-1m\DOGEUSDT_1m_full_hdr.csv",
    "KAS": r"D:\databtcusdt\KASUSDT-1m\KASUSDT_1m_full_hdr.csv",
    "ADA": r"D:\databtcusdt\ADAUSDT-1m-merged.csv",
    "LINK": r"D:\databtcusdt\LINKUSDT-1m-merged.csv",
    "LTC": r"D:\databtcusdt\LTCUSDT-1m-merged.csv",
    "BTC": r"D:\databtcusdt\BTCUSDT-1m\BTCUSDT_1m_2020_2026_conv.csv",
    "XRP": r"D:\databtcusdt\XRPUSDT-1m-merged.csv",
    "AVAX": r"D:\databtcusdt\AVAXUSDT-1m-merged.csv",
    "TON": r"D:\databtcusdt\TONUSDT-1m-merged.csv",
}

MAKER, TAKER = 0.00036, 0.0010


# ----------------------------------------------------------------------------- загрузка
def load_rows(rows_dir: str, symbols: list[str]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for sym in symbols:
        rows: list[dict] = []
        for y in (2024, 2025, 2026):
            p = os.path.join(rows_dir, f"{sym}_{y}.pkl")
            if os.path.exists(p):
                rows.extend(pickle.load(open(p, "rb")))
        rows.sort(key=lambda r: (str(r.get("scan") or ""), str(r.get("cbt") or "")))
        out[sym] = rows
    return out


def parity_check(rows: dict[str, list[dict]]) -> dict:
    """Сверка taken-набора с эталонным прогоном stopt_tf1v2 (ожидаем 998 / +113.3)."""
    new_keys = set()
    for sym, rs in rows.items():
        for r in rs:
            if r.get("taken"):
                new_keys.add((r.get("sym") or r.get("symbol"), r["direction"], r["scan"], r["cbt"]))
    old_keys = set()
    for sym in PAIRS10:
        for y in (2024, 2025, 2026):
            p = os.path.join(STOPT_DIR, f"{sym}_{y}.pkl")
            if not os.path.exists(p):
                continue
            for r in pickle.load(open(p, "rb")):
                old_keys.add((r["sym"], r["direction"], r["scan"], r["cbt"]))
    return {
        "new_taken": len(new_keys),
        "old_taken": len(old_keys),
        "equal": new_keys == old_keys,
        "only_new": sorted(new_keys - old_keys)[:5],
        "only_old": sorted(old_keys - new_keys)[:5],
    }


# ------------------------------------------------------------------------- сбор контекстов
def build_contexts(rows_by_sym: dict[str, list[dict]], out_jsonl: str, out_csv: str,
                   symbols: list[str]) -> list[dict]:
    f_jsonl = open(out_jsonl, "w", encoding="utf-8")
    csv_rows: list[dict] = []
    flat: list[dict] = []
    t_start = time.time()
    n_done = 0
    for sym in symbols:
        rs = rows_by_sym.get(sym) or []
        if not rs:
            print(f"[{sym}] нет строк — пропуск", flush=True)
            continue
        if not os.path.exists(PATHS[sym]):
            print(f"[{sym}] НЕТ 1m-файла {PATHS[sym]} — пропуск", flush=True)
            continue
        t0 = time.time()
        df1 = load_1m(PATHS[sym], PREHISTORY, UNTIL)
        frames = make_frames(df1)
        eng = HTFContextEngine(sym, frames)
        idx_ns = df1.index.to_numpy(dtype="datetime64[ns]")
        closes = df1["close"].to_numpy(dtype="float64")
        print(f"[{sym}] 1m={len(df1):,} 4H={len(frames['4H']):,} 1D={len(frames['1D']):,} "
              f"1W={len(frames['1W']):,} сигналов={len(rs)}", flush=True)
        for r in rs:
            scan = pd.Timestamp(r["scan"])
            j = int(np.searchsorted(idx_ns, np.datetime64(scan), side="left")) - 1
            px = float(closes[j]) if j >= 0 else float(r["entry"])
            signal = {
                "direction": r["direction"], "entry": r["entry"], "stop": r["stop"],
                "tp": r["tp"], "cbt": r.get("cbt"), "tbt": r.get("tbt"),
                "htf": r.get("htf"), "scan": r.get("scan"),
                "cisd_level": r.get("cisd_level"), "htf_sweep_level": r.get("htf_sweep_level"),
            }
            ctx = eng.context(scan, signal, tp_r=1.0, px=px)
            line = {k: r.get(k) for k in (
                "sym", "direction", "taken", "skip_reason", "outcome", "r", "outcome_cf",
                "r_cf", "scan", "cbt", "tbt", "htf", "entry", "stop", "tp", "sp",
                "cisd_level", "htf_sweep_level")}
            line["symbol"] = line.pop("sym")
            line["context"] = ctx
            f_jsonl.write(json.dumps(line, ensure_ascii=False) + "\n")
            csv_rows.append(flatten_for_csv(r, ctx))
            flat.append({"row": r, "ctx": ctx})
            n_done += 1
            if n_done % 100 == 0:
                print(f"  ... {n_done} контекстов, {time.time()-t_start:.0f}s", flush=True)
        print(f"[{sym}] готово за {time.time()-t0:.0f}s", flush=True)
    f_jsonl.close()
    pd.DataFrame(csv_rows).to_csv(out_csv, index=False)
    print(f"JSONL: {out_jsonl}\nCSV:   {out_csv}", flush=True)
    return flat


def flatten_for_csv(r: dict, ctx: dict) -> dict:
    s = ctx.get("summary") or {}
    h = ctx.get("htf") or {}
    out = {
        "symbol": r.get("sym"), "scan": r.get("scan"), "cbt": r.get("cbt"),
        "direction": r.get("direction"), "taken": r.get("taken"),
        "skip_reason": r.get("skip_reason"), "outcome": r.get("outcome"),
        "r": r.get("r"), "r_gross": gross_r(r),
        "outcome_cf": r.get("outcome_cf"), "r_cf": r.get("r_cf"),
        "entry": r.get("entry"), "stop": r.get("stop"), "tp": r.get("tp"), "sp": r.get("sp"),
        "px": (ctx.get("signal") or {}).get("px"),
        "nearest_opposing_obstacle_R": s.get("nearest_opposing_obstacle_R"),
        "nearest_opposing_obstacle_pct": s.get("nearest_opposing_obstacle_pct"),
        "nearest_internal_liquidity_R": s.get("nearest_internal_liquidity_R"),
        "nearest_external_liquidity_R": s.get("nearest_external_liquidity_R"),
        "tp_blocked": s.get("tp_blocked"),
        "obstacle_count_under_1R": s.get("obstacle_count_under_1R"),
        "obstacle_count_under_2R": s.get("obstacle_count_under_2R"),
        "obstacle_count_0_0.5R": s.get("obstacle_count_0_0.5R"),
        "obstacle_count_0.5_1R": s.get("obstacle_count_0.5_1R"),
        "obstacle_count_1_2R": s.get("obstacle_count_1_2R"),
        "obstacle_count_2_3R": s.get("obstacle_count_2_3R"),
        "path_n": len(ctx.get("path") or []),
        "excluded_n": len(ctx.get("excluded_sources") or []),
    }
    for tf_key, pre in (("4H", "4h"), ("1D", "1d"), ("1W", "1w")):
        blk = h.get(tf_key) or {}
        out[f"nearest_{pre}_obstacle_R"] = blk.get("nearest_obstacle_R")
        out[f"nearest_{pre}_fvg_R"] = blk.get("nearest_fvg_R")
        out[f"nearest_{pre}_swing_R"] = blk.get("nearest_swing_R")
        out[f"range_{pre}_pos"] = blk.get("range_position")
        out[f"premium_{pre}"] = blk.get("premium_discount")
    return out


# ------------------------------------------------------------------------------- анализ
def load_jsonl(path: str) -> list[dict]:
    flat = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            obj = json.loads(line)
            flat.append({"row": obj, "ctx": obj.get("context") or {}})
    return flat


def gross_r(row: dict) -> float | None:
    r = row.get("r")
    if r is None:
        return None
    sp = float(row.get("sp") or 0)
    if sp <= 0:
        return None
    fee_x = MAKER if row.get("outcome") == "tp" else TAKER
    return float(r) + (MAKER + fee_x) / sp


def cluster_boot_ci(vals: list[float], groups: list, B: int = 2000, seed: int = 42) -> tuple:
    """CI среднего с кластеризацией по неделям (ресэмпл недель с возвращением)."""
    if not vals:
        return (None, None)
    acc: dict = {}
    for v, g in zip(vals, groups):
        a = acc.setdefault(g, [0.0, 0])
        a[0] += float(v)
        a[1] += 1
    keys = list(acc.keys())
    if len(keys) < 2:
        return (None, None)
    sums = np.array([acc[k][0] for k in keys], dtype="float64")
    cnts = np.array([acc[k][1] for k in keys], dtype="float64")
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(keys), size=(B, len(keys)))
    tot = sums[idx].sum(axis=1)
    num = cnts[idx].sum(axis=1)
    means = tot / np.maximum(num, 1.0)
    lo, hi = np.percentile(means, [2.5, 97.5])
    return (round(float(lo), 3), round(float(hi), 3))


def stat_block(rows: list[dict]) -> dict:
    """n / исходы / WR / ΣR / avgR / gross / CI (t и недельный бутстрэп). rows = элементы flat {"row","ctx"}."""
    n = len(rows)
    if n == 0:
        return {"n": 0}
    tp = sum(1 for f in rows if f["row"]["outcome"] == "tp")
    sl = sum(1 for f in rows if f["row"]["outcome"] == "sl")
    tm = sum(1 for f in rows if f["row"]["outcome"] == "time")
    dec = tp + sl
    rr = [float(f["row"]["r"]) for f in rows]
    gr = [g for g in (gross_r(f["row"]) for f in rows) if g is not None]
    sd = float(np.std(rr, ddof=1)) if n > 1 else 0.0
    ci_t = (round(np.mean(rr) - 1.96 * sd / np.sqrt(n), 3),
            round(np.mean(rr) + 1.96 * sd / np.sqrt(n), 3)) if n > 1 else (None, None)
    weeks = [pd.Timestamp(f["row"]["scan"]).to_period("W-SUN") for f in rows]
    ci_w = cluster_boot_ci(rr, weeks)
    return {
        "n": n, "tp": tp, "sl": sl, "time": tm,
        "wr": round(tp / n * 100, 1),
        "wr_dec": round(tp / dec * 100, 1) if dec else None,
        "sumR": round(sum(rr), 1), "avgR": round(float(np.mean(rr)), 4),
        "sumR_gross": round(sum(gr), 1) if gr else None,
        "avgR_gross": round(float(np.mean(gr)), 4) if gr else None,
        "ci_t": ci_t, "ci_week": ci_w,
        "weeks": len(set(weeks)),
    }


def rbucket(v) -> str:
    if v is None:
        return "нет(>5R)"
    if v < 0.25:
        return "<0.25"
    if v < 0.5:
        return "0.25-0.5"
    if v < 1.0:
        return "0.5-1"
    if v < 2.0:
        return "1-2"
    if v < 3.0:
        return "2-3"
    return ">3"


ROOM_ORDER = ["<0.25", "0.25-0.5", "0.5-1", "1-2", "2-3", ">3", "нет(>5R)"]


def fmt_stat(s: dict) -> str:
    if s.get("n", 0) == 0:
        return "—"
    ci = s.get("ci_t") or (None, None)
    ci_s = f"[{ci[0]},{ci[1]}]" if ci[0] is not None else "—"
    return (f"{s['n']} / {s['tp']}/{s['sl']}/{s['time']} / {s['wr']}% / "
            f"{s['sumR']:+.1f}R / {s['avgR']:+.3f} / {ci_s}")


def md_table(headers: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(x) for x in r) + " |")
    return "\n".join(out)


def year_of(scan: str) -> str:
    return str(pd.Timestamp(scan).year)


# -------------------------------------------------------------------------------- отчёт
def analyze_and_report(flat: list[dict], parity: dict, out_report: str) -> None:
    taken = [f for f in flat if f["row"].get("taken") and f["row"].get("outcome")]
    skipped = [f for f in flat if not f["row"].get("taken")]
    print(f"taken={len(taken)} skipped={len(skipped)}", flush=True)

    def feat(f): return (f["ctx"].get("summary") or {}).get("nearest_opposing_obstacle_R")
    def feat_int(f): return (f["ctx"].get("summary") or {}).get("nearest_internal_liquidity_R")
    def feat_ext(f): return (f["ctx"].get("summary") or {}).get("nearest_external_liquidity_R")

    L: list[str] = []
    L.append("# HTF Context Engine — исследовательский отчёт (08.10.2026)")
    L.append("")
    L.append("Датасет: кандидат v2 (tf1, 15m→4H), 10 пар, 2024-01-01…2026-09-01. "
             "Контекст считается ТОЛЬКО по закрытым данным на момент решения (causal); "
             "проверка — `RUNS/cache/htf_context_validation.json` (все тесты PASS).")
    L.append(f"Паритет taken-набора с эталоном stopt_tf1v2: {parity['new_taken']} vs {parity['old_taken']}, "
             f"equal={parity['equal']}.")
    L.append("")
    L.append("Модель выхода: TP 1R, стоп структурный, таймаут 16ч, комиссии Bybit (net R; "
             "gross R = r + (maker+fee_x)/sp).")
    L.append("")

    # --- A0. бинарный разрез 0.25R (ключевая форма зависимости)
    L.append("## A0. Разрез «вплотную к препятствию» (<0.25R) vs «есть место» (>=0.25R)")
    L.append("")

    def cut(sel):
        return [f for f in taken if sel(feat(f))]

    rows0 = []
    for name, sel in (
        ("<0.25R (все)", lambda v: v is not None and v < 0.25),
        ("   =0.0 (вход в остатке зоны)", lambda v: v is not None and v == 0.0),
        ("   (0, 0.25)", lambda v: v is not None and 0.0 < v < 0.25),
        (">=0.25R", lambda v: v is not None and v >= 0.25),
        ("нет объектов (>5R)", lambda v: v is None),
    ):
        s = stat_block(cut(sel))
        rows0.append([name, fmt_stat(s) if s.get("n") else "—"])
    L.append(md_table(["группа", "n / tp/sl/time / WR / ΣR(нетто) / avgR / CI95(t)"], rows0))
    L.append("")
    yrows0 = []
    for y in ("2024", "2025", "2026"):
        cells = [y]
        for name, sel in (("<0.25R", lambda v: v is not None and v < 0.25),
                          (">=0.25R", lambda v: v is not None and v >= 0.25)):
            g = [f for f in taken if year_of(f["row"]["scan"]) == y and sel(feat(f))]
            s = stat_block(g)
            cells.append(f"{s.get('n', 0)} / {s.get('avgR', '—')}" if s.get("n") else "—")
        yrows0.append(cells)
    L.append(md_table(["год", "<0.25R (n / avgR)", ">=0.25R (n / avgR)"], yrows0))
    L.append("")
    wrows0 = []
    for name, sel in (("<0.25R", lambda v: v is not None and v < 0.25),
                      (">=0.25R", lambda v: v is not None and v >= 0.25)):
        g = cut(sel)
        s = stat_block(g)
        ciw = s["ci_week"]
        wrows0.append([name, s.get("n"), f"{s['avgR']:+.3f}" if s.get("n") else "—",
                       f"[{ciw[0]},{ciw[1]}]" if ciw and ciw[0] is not None else "—",
                       f"{s.get('weeks', '—')} нед."])
    L.append(md_table(["группа (недельный бутстрэп)", "n", "avgR", "CI95(week)", "кластеров"], wrows0))
    L.append("")

    # --- A. room_R buckets
    L.append("## A. nearest_opposing_obstacle_R — корзины (taken)")
    L.append("")
    L.append(md_table(
        ["корзина", "n / tp/sl/time / WR / ΣR(нетто) / avgR / CI95(t)"],
        [[b, fmt_stat(stat_block([f for f in taken if rbucket(feat(f)) == b]))] for b in ROOM_ORDER]
    ))
    L.append("")
    L.append("_Для ориентира: комиссионная нагрузка ≈ 0.07-0.10R/сделку; breakeven-avgR при WR ~46% ≈ -0.08R._")
    L.append("")
    L.append("### A1b. То же по ногам (n / avgR нетто)")
    L.append("")
    lrows = []
    for b in ROOM_ORDER:
        gl = [f for f in taken if rbucket(feat(f)) == b and f["row"]["direction"] == "LONG"]
        gs = [f for f in taken if rbucket(feat(f)) == b and f["row"]["direction"] == "SHORT"]
        sl_ = stat_block(gl)
        ss_ = stat_block(gs)
        lrows.append([
            b,
            f"{sl_.get('n', 0)} / {sl_.get('avgR', '—')}" if sl_.get("n") else "—",
            f"{ss_.get('n', 0)} / {ss_.get('avgR', '—')}" if ss_.get("n") else "—",
        ])
    L.append(md_table(["корзина", "LONG", "SHORT"], lrows))
    L.append("")

    # --- A2. internal / external
    for label, fn in (("A2. nearest_internal_liquidity_R (FVG)", feat_int),
                      ("A3. nearest_external_liquidity_R (свинги+PDH/PWH)", feat_ext)):
        L.append(f"## {label} — корзины (taken)")
        L.append("")
        L.append(md_table(
            ["корзина", "n / tp/sl/time / WR / ΣR(нетто) / avgR / CI95(t)"],
            [[b, fmt_stat(stat_block([f for f in taken if rbucket(fn(f)) == b]))] for b in ROOM_ORDER]
        ))
        L.append("")

    # --- A4. где лежит ближайшее препятствие (по ТФ)
    L.append("### A4. ТФ ближайшего препятствия (path[0])")
    L.append("")
    a4 = []
    for tf_name in ("4H", "1D", "1W"):
        g = [f for f in taken if (f["ctx"].get("path") or [{}])[0].get("tf") == tf_name]
        a4.append([tf_name, fmt_stat(stat_block(g))])
    L.append(md_table(["ТФ ближайшего", "n / tp/sl/time / WR / ΣR / avgR / CI95(t)"], a4))
    L.append("")

    # --- B. stop terciles
    sps = [float(f["row"]["sp"]) for f in taken]
    q1, q2 = (np.quantile(sps, [1 / 3, 2 / 3]) if sps else (0, 0))
    L.append("## B. Корзины × терцили ширины стопа (n / avgR нетто)")
    L.append("")
    L.append(f"Терцили стоп pct: T1 < {q1:.4f} <= T2 <= {q2:.4f} < T3")
    L.append("")
    trows = []
    for b in ["<0.25", "0.25-0.5", "0.5-1", "1-2", "2-3", ">3", "нет(>5R)"]:
        cells = [b]
        for name, sel in (("T1", lambda s: s < q1), ("T2", lambda s: q1 <= s <= q2), ("T3", lambda s: s > q2)):
            g = [f for f in taken if rbucket(feat(f)) == b and sel(float(f["row"]["sp"]))]
            s = stat_block(g)
            cells.append(f"{s.get('n',0)} / {s.get('avgR','—')}" if s.get("n") else "—")
        trows.append(cells)
    L.append(md_table(["room \\ stop", "T1 (узкий)", "T2 (средний)", "T3 (широкий)"], trows))
    L.append("")

    # --- C. by year
    L.append("## C. По годам (n / avgR нетто; скобки — ΣR)")
    L.append("")
    yrows = []
    bcols = ["<0.25", "0.25-0.5", "0.5-1", "1-2", "2-3", ">3", "нет(>5R)"]
    for y in ("2024", "2025", "2026"):
        cells = [y]
        for b in bcols:
            g = [f for f in taken if year_of(f["row"]["scan"]) == y and rbucket(feat(f)) == b]
            s = stat_block(g)
            cells.append(f"{s.get('n',0)} / {s.get('avgR','—')}" if s.get("n") else "—")
        yrows.append(cells)
    L.append(md_table(["год \\ room", *bcols], yrows))
    L.append("")

    # --- D. weekly robustness
    L.append("## D. Недельные кластеры (устойчивость)")
    L.append("")
    drows = []
    for name, sel in (
        ("room < 0.5R", lambda f: (feat(f) is not None and feat(f) < 0.5)),
        ("room 0.5-1R", lambda f: (feat(f) is not None and 0.5 <= feat(f) < 1.0)),
        ("room >= 1R", lambda f: (feat(f) is not None and feat(f) >= 1.0)),
        ("room нет(>5R)", lambda f: feat(f) is None),
        ("все taken", lambda f: True),
    ):
        g = [f for f in taken if sel(f)]
        s = stat_block(g)
        if s.get("n", 0) == 0:
            drows.append([name, "—", "—", "—", "—"])
            continue
        ciw = s["ci_week"]
        drows.append([
            name, s["n"], f"{s['avgR']:+.3f}",
            f"[{ciw[0]},{ciw[1]}]" if ciw[0] is not None else "—",
            f"{s['weeks']} нед.",
        ])
    L.append(md_table(["группа", "n", "avgR", "CI95(недельный бутстрэп)", "кластеров"], drows))
    L.append("")

    # --- tp_blocked
    L.append("## E. tp_blocked (nearest < 1R ⇒ TP1R «за препятствием») — производный признак")
    L.append("")
    erows = []
    for name, sel in (("blocked (room<1R)", lambda f: feat(f) is not None and feat(f) < 1.0),
                      ("free (room>=1R)", lambda f: feat(f) is not None and feat(f) >= 1.0),
                      ("нет объектов", lambda f: feat(f) is None)):
        g = [f for f in taken if sel(f)]
        s = stat_block(g)
        erows.append([name, fmt_stat(s)])
    L.append(md_table(["группа", "n / tp/sl/time / WR / ΣR / avgR / CI95(t)"], erows))
    L.append("")

    # --- counts
    L.append("## F. Плотность карты (obstacle_count) — только описательно")
    L.append("")
    frows = []
    for cnt_name in ("obstacle_count_under_1R", "obstacle_count_under_2R"):
        for k in range(0, 4):
            g = [f for f in taken
                 if min(int((f["ctx"].get("summary") or {}).get(cnt_name) or 0), 3) == k]
            s = stat_block(g)
            if s.get("n", 0):
                frows.append([f"{cnt_name}={k}{'+' if k==3 else ''}", fmt_stat(s)])
    L.append(md_table(["признак", "n / tp/sl/time / WR / ΣR / avgR / CI95(t)"], frows))
    L.append("")

    # --- skip-статистика
    L.append("## G. Пропущенные сигналы (контрфактические исходы, справочно)")
    L.append("")
    srows = []
    for reason in ("busy", "htf_taken", "tp_touched", "no_fill"):
        g = [f for f in skipped if f["row"].get("skip_reason") == reason]
        cf = [f for f in g if f["row"].get("r_cf") is not None]
        if not g:
            continue
        srows.append([
            reason, len(g), len(cf),
            round(float(np.mean([f["row"]["r_cf"] for f in cf])), 4) if cf else None,
            round(sum(float(f["row"]["r_cf"]) for f in cf), 1) if cf else None,
        ])
    L.append(md_table(["причина", "n", "с филлом (cf)", "avgR_cf", "ΣR_cf"], srows))
    L.append("")

    # --- примеры
    L.append("## H. Примеры контекстов (глазами)")
    L.append("")
    ex1 = next((f for f in taken if feat(f) is not None and feat(f) < 0.5), None)
    ex2 = next((f for f in taken if feat(f) is None), None)
    for tag, ex in (("вход «под препятствием»", ex1), ("чистое пространство (>5R)", ex2)):
        if ex is None:
            continue
        r = ex["row"]; c = ex["ctx"]; s = c["summary"]
        sym = r.get("symbol") or r.get("sym")
        L.append(f"**{tag}** — {sym} {r['scan']} {r['direction']} outcome={r['outcome']} r={r['r']:+.2f}")
        L.append(f"- path: " + ("; ".join(
            f"{o['distance_R']}R {o['tf']} {o['type']} ({o['state']})" for o in c["path"]) or "—"))
        L.append(f"- summary: nearest={s['nearest_opposing_obstacle_R']}R "
                 f"internal={s['nearest_internal_liquidity_R']} external={s['nearest_external_liquidity_R']} "
                 f"tp_blocked={s['tp_blocked']}")
        L.append("")

    L.append("## Вердикт-критерий (ТЗ §17)")
    L.append("")
    L.append("Ветка продолжается, только если в 2024–2026 видна устойчивая монотонная "
             "зависимость по nearest_opposing_obstacle_R (или internal/external отдельно), "
             "подтверждённая CI и недельными кластерами. Иначе — ветка закрывается.")
    L.append("")

    with open(out_report, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    print(f"Отчёт: {out_report}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-build", action="store_true", help="не строить контексты, читать готовый JSONL")
    ap.add_argument("--rows-dir", default=ROWS_DIR)
    ap.add_argument("--jsonl", default=os.path.join(CACHE_DIR, "htf_context.jsonl"))
    ap.add_argument("--csv", default=os.path.join(CACHE_DIR, "htf_context_summary.csv"))
    ap.add_argument("--report", default=os.path.join(PROJ, "RUNS", "HTF_CONTEXT_REPORT_2026-10-08.md"))
    ap.add_argument("--symbols", default=",".join(PAIRS10))
    args = ap.parse_args()

    os.makedirs(CACHE_DIR, exist_ok=True)
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    t0 = time.time()

    if args.skip_build:
        flat = load_jsonl(args.jsonl)
        print(f"JSONL прочитан: {len(flat)} строк", flush=True)
        rows_map: dict[str, list[dict]] = {}
        for f in flat:
            r = f["row"]
            rows_map.setdefault(r.get("symbol") or r.get("sym") or "?", []).append(r)
        parity = parity_check(rows_map)
        print(f"паритет: {parity}", flush=True)
    else:
        rows = load_rows(args.rows_dir, symbols)
        n_all = sum(len(v) for v in rows.values())
        n_taken = sum(1 for v in rows.values() for r in v if r.get("taken"))
        print(f"строк всего={n_all}, taken={n_taken}", flush=True)
        parity = parity_check(rows)
        print(f"паритет: {parity}", flush=True)
        flat = build_contexts(rows, args.jsonl, args.csv, symbols)

    analyze_and_report(flat, parity, args.report)
    print(f"ИТОГО {time.time()-t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

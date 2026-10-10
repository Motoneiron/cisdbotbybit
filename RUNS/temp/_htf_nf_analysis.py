# -*- coding: utf-8 -*-
"""Анализ NOFILTER-прогона кандидата v2 (вопрос юзера 08.10: «фильтры отсеяли хорошие сделки?»).

Вход:
  RUNS/temp/live_tf_htfctx_nf/rows_tf1v2_nofilter/*.pkl — поток без 4 фильтров (теги + cf)
  RUNS/temp/live_tf_htfctx/rows_tf1v2/*.pkl            — база кандидата (для сверки/сравнения)
Выход:
  RUNS/cache/nofilter_summary.csv                     — плоская таблица nofilter-строк + room-фичи
  RUNS/NOFILTER_ANALYSIS_2026-10-09.md                — отчёт

Запуск: python _htf_nf_analysis.py [--skip-context]
"""
from __future__ import annotations

import argparse
import glob
import os
import pickle
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, r"D:\PYTHON\cisdbotbybit")

from HTF_CONTEXT.htf_context import HTFContextEngine
from HTF_CONTEXT.htf_resample import load_1m, make_frames
from HTF_CONTEXT.research_htf_context import stat_block, md_table, gross_r, PAIRS10, PATHS, PREHISTORY, UNTIL

NF_DIR = r"D:\PYTHON\cisdbotbybit\RUNS\temp\live_tf_htfctx_nf\rows_tf1v2_nofilter"
BASE_DIR = r"D:\PYTHON\cisdbotbybit\RUNS\temp\live_tf_htfctx\rows_tf1v2"
OUT_CSV = r"D:\PYTHON\cisdbotbybit\RUNS\cache\nofilter_summary.csv"
OUT_MD = r"D:\PYTHON\cisdbotbybit\RUNS\NOFILTER_ANALYSIS_2026-10-09.md"

TAGS = ("gate_rej", "ms_rej", "dt_rej", "sweep_rej")


def load_rows(d: str) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for f in sorted(glob.glob(os.path.join(d, "*.pkl"))):
        sym = os.path.basename(f).rsplit("_", 1)[0]
        if sym not in PAIRS10:
            continue
        out.setdefault(sym, []).extend(pickle.load(open(f, "rb")))
    for s in out:
        out[s].sort(key=lambda r: (str(r.get("scan") or ""), str(r.get("cbt") or "")))
    return out


def any_tag(r: dict) -> bool:
    return any(bool(r.get(t)) for t in TAGS)


def first_stage(r: dict) -> str:
    """Первый отсекающий этап в базовом порядке: gate -> min_stop -> dt -> sweep."""
    if r.get("gate_rej"):
        return "gate"
    if r.get("ms_rej"):
        return "min_stop"
    if r.get("dt_rej"):
        return "dt>=2h"
    if r.get("sweep_rej"):
        return "sweep_valid"
    return "pass"


def y_or(scan) -> str:
    return str(pd.Timestamp(scan).year)


def flat_of(rows: list[dict]) -> list[dict]:
    return [{"row": r, "ctx": r.get("_ctx") or {}} for r in rows]


def fmt(s: dict) -> str:
    if not s.get("n"):
        return "—"
    ci = s.get("ci_t") or (None, None)
    ci_s = f"[{ci[0]},{ci[1]}]" if ci[0] is not None else "—"
    wr = f"{s['wr']}%"
    return (f"{s['n']} / {s['tp']}/{s['sl']}/{s['time']} / {wr} / {s['sumR']:+.1f}R / "
            f"{s['avgR']:+.3f} / {ci_s}")


def fmt_cf(rows: list[dict]) -> str:
    """Контрфактическая сводка по сигналам с филлом (outcome_cf)."""
    cf = [r for r in rows if r.get("r_cf") is not None]
    if not cf:
        return f"n={len(rows)} / филлов 0"
    rr = [float(r["r_cf"]) for r in cf]
    tp = sum(1 for r in cf if r.get("outcome_cf") == "tp")
    sl = sum(1 for r in cf if r.get("outcome_cf") == "sl")
    return (f"{len(rows)} / филлов {len(cf)} ({len(cf)/len(rows)*100:.0f}%) / "
            f"WR {tp/(len(cf))*100:.1f}% (tp/sl={tp}/{sl}) / ΣR_cf {sum(rr):+.1f} / avgR_cf {np.mean(rr):+.3f}")


def room_of(r: dict):
    c = r.get("_ctx") or {}
    s = c.get("summary") or {}
    return s.get("nearest_opposing_obstacle_R")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-context", action="store_true")
    args = ap.parse_args()
    t_start = time.time()

    nf = load_rows(NF_DIR)
    base = load_rows(BASE_DIR)
    nf_rows = [r for rows in nf.values() for r in rows]
    base_rows = [r for rows in base.values() for r in rows]
    print(f"nofilter: {len(nf_rows)} строк | base: {len(base_rows)} строк", flush=True)

    # ---- sanity: all-tags-false == base decision set
    nf_pass = {(r["sym"], r["direction"], r["scan"], r["cbt"]) for r in nf_rows if not any_tag(r)}
    base_keys = {(r["sym"], r["direction"], r["scan"], r["cbt"]) for r in base_rows}
    sanity_ok = nf_pass == base_keys
    print(f"СВЕРКА: сигналов, прошедших все 4 фильтра: {len(nf_pass)}; в базе: {len(base_keys)}; equal={sanity_ok}", flush=True)

    # ---- контексты для нужных строк: taken ИЛИ (тег И филл)
    need = [r for r in nf_rows if r.get("taken") or (any_tag(r) and r.get("r_cf") is not None)]
    print(f"контексты нужны для {len(need)} строк", flush=True)
    if not args.skip_context:
        by_sym: dict[str, list[dict]] = {}
        for r in need:
            by_sym.setdefault(r["sym"], []).append(r)
        for sym, rows in by_sym.items():
            if not os.path.exists(PATHS[sym]):
                continue
            t0 = time.time()
            df1 = load_1m(PATHS[sym], PREHISTORY, UNTIL)
            frames = make_frames(df1)
            eng = HTFContextEngine(sym, frames)
            idx_ns = df1.index.to_numpy(dtype="datetime64[ns]")
            closes = df1["close"].to_numpy(dtype="float64")
            for r in rows:
                scan = pd.Timestamp(r["scan"])
                j = int(np.searchsorted(idx_ns, np.datetime64(scan), side="left")) - 1
                px = float(closes[j]) if j >= 0 else float(r["entry"])
                signal = {
                    "direction": r["direction"], "entry": r["entry"], "stop": r["stop"],
                    "tp": r["tp"], "cbt": r.get("cbt"), "tbt": r.get("tbt"),
                    "htf": r.get("htf"), "scan": r.get("scan"),
                    "cisd_level": r.get("cisd_level"), "htf_sweep_level": r.get("htf_sweep_level"),
                }
                r["_ctx"] = eng.context(scan, signal, tp_r=1.0, px=px)
            print(f"[{sym}] контекстов {len(rows)} за {time.time()-t0:.0f}s", flush=True)

    # ---- CSV
    csv_rows = []
    for r in nf_rows:
        s = (r.get("_ctx") or {}).get("summary") or {}
        csv_rows.append({
            "symbol": r["sym"], "scan": r["scan"], "cbt": r.get("cbt"), "direction": r["direction"],
            "taken": bool(r.get("taken")), "skip_reason": r.get("skip_reason"),
            "stage": first_stage(r), "gate_rej": r.get("gate_rej"), "ms_rej": r.get("ms_rej"),
            "dt_rej": r.get("dt_rej"), "sweep_rej": r.get("sweep_rej"),
            "sv": r.get("sv"), "c2c_min": r.get("c2c_min"), "sp_pct": r.get("sp_pct"),
            "sp": r.get("sp"), "entry": r.get("entry"), "stop": r.get("stop"), "tp": r.get("tp"),
            "outcome": r.get("outcome"), "r": r.get("r"),
            "outcome_cf": r.get("outcome_cf"), "r_cf": r.get("r_cf"),
            "nearest_opposing_R": s.get("nearest_opposing_obstacle_R"),
            "nearest_internal_R": s.get("nearest_internal_liquidity_R"),
            "nearest_external_R": s.get("nearest_external_liquidity_R"),
            "tp_blocked": s.get("tp_blocked"),
        })
    pd.DataFrame(csv_rows).to_csv(OUT_CSV, index=False)
    print(f"CSV: {OUT_CSV}", flush=True)

    # ================================================================ отчёт
    L: list[str] = []
    L.append("# NOFILTER-прогон кандидата v2 — «что было бы без фильтров» (09.10.2026)")
    L.append("")
    L.append("Прогон: те же данные/детектор/механика (busy, htf_taken, tp_touched, лимитка 1ч, позиция 16ч, TP1R),")
    L.append("НО без четырёх пользовательских фильтров: гейт EMA21(15m, lc), min_stop 1.5%, «конфирм ≥2ч от свипа», sweep-валидация.")
    L.append(f"Сверка честности потока: сигналов, прошедших все 4 фильтра = {len(nf_pass)}; база = {len(base_keys)}; equal={sanity_ok}.")
    L.append("")

    taken_nf = [r for r in nf_rows if r.get("taken") and r.get("r") is not None]
    taken_base = [r for r in base_rows if r.get("taken") and r.get("r") is not None]

    # --- T1: результат
    L.append("## T1. Результат потока (taken, с busy-механикой)")
    L.append("")
    rows1 = []
    for name, rs in (("БАЗА (кандидат v2)", taken_base), ("БЕЗ ФИЛЬТРОВ", taken_nf)):
        s = stat_block(flat_of(rs))
        rows1.append([name, fmt(s)])
    L.append(md_table(["поток", "n / tp/sl/time / WR / ΣR(нетто) / avgR / CI95(t)"], rows1))
    L.append("")
    L.append("По годам (n / avgR):")
    L.append("")
    rows1y = []
    for y in ("2024", "2025", "2026"):
        cells = [y]
        for name, rs in (("база", taken_base), ("без фильтров", taken_nf)):
            g = [r for r in rs if y_or(r["scan"]) == y]
            s = stat_block(flat_of(g))
            cells.append(f"{s.get('n',0)} / {s.get('avgR','—')}" if s.get("n") else "—")
        rows1y.append(cells)
    L.append(md_table(["год", "база", "без фильтров"], rows1y))
    L.append("")
    rows1l = []
    for leg in ("LONG", "SHORT"):
        cells = [leg]
        for name, rs in (("база", taken_base), ("без фильтров", taken_nf)):
            g = [r for r in rs if r["direction"] == leg]
            s = stat_block(flat_of(g))
            cells.append(f"{s.get('n',0)} / {s.get('avgR','—')} / {s.get('sumR','—')}R" if s.get("n") else "—")
        rows1l.append(cells)
    L.append(md_table(["нога", "база (n/avgR/ΣR)", "без фильтров (n/avgR/ΣR)"], rows1l))
    L.append("")

    # --- T2: что отсекали фильтры (по первому отсекающему этапу базового порядка)
    L.append("## T2. Что отсекал каждый фильтр (контрфактика: исход, если бы взяли с тем же входом)")
    L.append("")
    L.append("_Контрфактика считается по каждому сигналу отдельно (лимитка 1ч, TP1R, 16ч) — это «качество сделки самого по себе», без конкуренции за слот (busy)._")
    L.append("")
    cut_rows = []
    for stage in ("gate", "min_stop", "dt>=2h", "sweep_valid"):
        g = [r for r in nf_rows if first_stage(r) == stage]
        cut_rows.append([stage, fmt_cf(g)])
    g_pass_untaken = [r for r in nf_rows if first_stage(r) == "pass" and not r.get("taken")]
    cut_rows.append(["(прошли фильтры, но busy/htf/no_fill)", fmt_cf(g_pass_untaken)])
    L.append(md_table(["фильтр", "сигналов / филлов / WR_cf / ΣR_cf / avgR_cf"], cut_rows))
    L.append("")
    L.append("По годам (avgR_cf, в скобках — филлов):")
    L.append("")
    rows2y = []
    for stage in ("gate", "min_stop", "dt>=2h", "sweep_valid"):
        cells = [stage]
        for y in ("2024", "2025", "2026"):
            g = [r for r in nf_rows if first_stage(r) == stage and y_or(r["scan"]) == y]
            cf = [float(r["r_cf"]) for r in g if r.get("r_cf") is not None]
            cells.append(f"{np.mean(cf):+.3f} ({len(cf)})" if cf else "—")
        rows2y.append(cells)
    L.append(md_table(["фильтр", "2024", "2025", "2026"], rows2y))
    L.append("")

    # --- T3: отсечённые × room
    L.append("## T3. Отсечённые фильтрами × место до препятствия (avgR_cf; n)")
    L.append("")
    def rb(v):
        if v is None:
            return "нет"
        if v < 0.25:
            return "<0.25"
        if v < 1.0:
            return "0.25-1"
        return ">=1"
    rows3 = []
    for stage in ("gate", "min_stop", "dt>=2h", "sweep_valid"):
        cells = [stage]
        for b in ("<0.25", "0.25-1", ">=1", "нет"):
            g = [r for r in nf_rows if first_stage(r) == stage and rb(room_of(r)) == b and r.get("r_cf") is not None]
            cells.append(f"{np.mean([float(r['r_cf']) for r in g]):+.3f} ({len(g)})" if g else "—")
        rows3.append(cells)
    # и nofilter-taken для сравнения
    cells = ["taken без фильтров"]
    for b in ("<0.25", "0.25-1", ">=1", "нет"):
        g = [r for r in taken_nf if rb(room_of(r)) == b and r.get("r") is not None]
        cells.append(f"{np.mean([float(r['r']) for r in g]):+.3f} ({len(g)})" if g else "—")
    rows3.append(cells)
    L.append(md_table(["группа \\ room", "<0.25R", "0.25-1R", ">=1R", "нет(>5R)"], rows3))
    L.append("")

    # --- T4: куда делись базовые сделки в плотном потоке
    L.append("## T4. Базовые 998 сделок внутри nofilter-потока (вытеснение)")
    L.append("")
    nf_by_key = {(r["sym"], r["direction"], r["scan"], r["cbt"]): r for r in nf_rows}
    stat: dict[str, int] = {}
    for r in taken_base:
        k = (r["sym"], r["direction"], r["scan"], r["cbt"])
        rr = nf_by_key.get(k)
        if rr is None:
            stat["не найден"] = stat.get("не найден", 0) + 1
        elif rr.get("taken"):
            stat["взят и без фильтров"] = stat.get("взят и без фильтров", 0) + 1
        else:
            stat[rr.get("skip_reason") or "?"] = stat.get(rr.get("skip_reason") or "?", 0) + 1
    L.append(md_table(["статус базовой сделки в nofilter", "n"], [[k, v] for k, v in sorted(stat.items())]))
    L.append("")

    L.append("## Как читать")
    L.append("")
    L.append("- T1 = «результат, если просто снять фильтры и торговать поток» (со всеми остальными правилами).")
    L.append("- T2 = качество ОТСЕЧЁННЫХ сигналов: avgR_cf ≈ 0 или минус ⇒ фильтр защищал; плюс ⇒ фильтр резал добро.")
    L.append("- T3 = были ли среди отсечённых хорошие ПО СТРУКТУРЕ (room) — не спрятано ли что-то стоящее.")
    L.append("- T4 = сколько базовых сделок «вытесняется», когда поток плотный (busy на пару).")
    L.append("")

    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    print(f"Отчёт: {OUT_MD}", flush=True)
    print(f"ИТОГО {time.time()-t_start:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Портфельная симуляция tf7-стека (на BASE_rerun: полные трейды с временами).

Пул 10 пар, TP=1R-модель, LIMIT-only.
Событийная симуляция: общий лимит слотов (None / 7 / 5), риск 1% эквити на сделку,
компаунд. Ставки: MEXC (r_net_mexc) и Bybit (пересчёт). Старт $100.
Вывод: финальное эквити, доходность, макс. просадка, взятые/пропущенные, по годам.
"""
import glob
import pickle
import sys

import pandas as pd

BASE = r"D:/PYTHON/cisdbotbybit/RUNS/temp"
CFG = sys.argv[1] if len(sys.argv) > 1 else "BASE_rerun"

def _fr(kind, outcome, spx, maker, taker):
    if not spx or spx <= 0:
        return 0.0
    e = maker if str(kind).upper() == "LIMIT" else taker
    x = maker if outcome == "tp" else taker
    return (e + x) / spx

rows = []
for f in glob.glob(BASE + "/tf7_abl/" + CFG + "_*.pkl"):
    rows.extend(pickle.load(open(f, "rb")))
d = pd.DataFrame(rows)
print("конфиг:", CFG, "| сделок всего:", len(d))
d["entry_ts"] = pd.to_datetime(d["entry_ts"], errors="coerce")
d["exit_ts"] = pd.to_datetime(d["exit_ts"], errors="coerce")
bad = d["entry_ts"].isna().sum() + d["exit_ts"].isna().sum()
print("без времени:", bad)
d = d.dropna(subset=["entry_ts", "exit_ts"]).copy()
d["r_byb"] = d["r_net_mexc"] + [
    _fr(k, o, s, 0.0006, 0.0008) - _fr(k, o, s, 0.00036, 0.0010)
    for k, o, s in zip(d.entry_kind, d.outcome, d.sp)
]
d = d.sort_values("entry_ts").reset_index(drop=True)

def simulate(d, cap, col, risk_frac=0.01, start=100.0):
    eq = start
    open_risk = []          # [(exit_ts, risk_amt, r_net, year_exit)]
    taken = skipped = 0
    eq_curve = [(d["entry_ts"].iloc[0], eq)]
    per_year = {}
    max_eq = start
    max_dd = 0.0
    def close_due(ts):
        nonlocal eq, max_eq, max_dd
        still = []
        for ex, ramt, rv, yr in open_risk:
            if ex <= ts:
                eq += ramt * rv
                per_year[yr] = per_year.get(yr, 0.0) + ramt * rv
                max_eq = max(max_eq, eq)
                dd = (max_eq - eq) / max_eq
                max_dd = max(max_dd, dd)
            else:
                still.append((ex, ramt, rv, yr))
        open_risk[:] = still
    for _, t in d.iterrows():
        close_due(t["entry_ts"])
        if cap is not None and len(open_risk) >= cap:
            skipped += 1
            continue
        taken += 1
        ramt = eq * risk_frac
        open_risk.append((t["exit_ts"], ramt, float(t[col]), t["exit_ts"].year))
        eq_curve.append((t["entry_ts"], eq))
    close_due(pd.Timestamp("2100-01-01"))
    roc = (eq / start - 1.0) * 100
    return {"cap": cap, "col": col, "taken": taken, "skipped": skipped,
            "final_eq": round(eq, 2), "roc_pct": round(roc, 1), "max_dd_pct": round(100 * max_dd, 1),
            "per_year_pnl": {k: round(v, 2) for k, v in sorted(per_year.items())}}

print("\n=== ПОРТФЕЛЬ (риск 1%/сделку, старт $100) ===")
for col in ("r_net_mexc", "r_byb"):
    for cap in (None, 7, 5):
        r = simulate(d, cap, col)
        print(f"{col} cap={cap}: взято {r['taken']} пропущено {r['skipped']} | "
              f"$100 -> ${r['final_eq']} ({r['roc_pct']:+.1f}%) | maxDD {r['max_dd_pct']}%")
        print("   по годам (PnL $):", r["per_year_pnl"])

# отдельно 2024-26 (актуальный режим)
d2 = d[d["entry_ts"] >= "2024-01-01"]
print("\n=== 2024-2026 ===")
for col in ("r_net_mexc", "r_byb"):
    for cap in (None, 7, 5):
        r = simulate(d2, cap, col)
        print(f"{col} cap={cap}: взято {r['taken']} пропущено {r['skipped']} | "
              f"$100 -> ${r['final_eq']} ({r['roc_pct']:+.1f}%) | maxDD {r['max_dd_pct']}%")

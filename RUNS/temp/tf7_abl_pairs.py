"""По-паровой разрез tf7: ABL_MSS_MAIN (канон) vs BASE_rerun (1m-MSS).
Вывод: по парам — все годы и 24-26 (MEXC и Bybit), стабильность по годам 24/25/26.
"""
import glob
import os
import pickle

import pandas as pd

BASE = r"D:/PYTHON/cisdbotbybit/RUNS/temp"
rows = []
for f in glob.glob(BASE + "/tf7_abl/*.pkl"):
    b = os.path.basename(f)
    cfg_name = None
    if b.startswith("ABL_MSS_MAIN_"):
        cfg_name = "ABL_MSS_MAIN"
    elif b.startswith("BASE_rerun_"):
        cfg_name = "BASE_rerun"
    if not cfg_name:
        continue
    sym_name = b[len(cfg_name) + 1:].split("_")[0]
    chunk = pickle.load(open(f, "rb"))
    for r in chunk:
        r["_sym"] = sym_name
    rows.extend(chunk)
d = pd.DataFrame(rows)

def _fr(kind, outcome, spx, maker, taker):
    if not spx or spx <= 0:
        return 0.0
    e = maker if str(kind).upper() == "LIMIT" else taker
    x = maker if outcome == "tp" else taker
    return (e + x) / spx

d["r_byb"] = d["r_net_mexc"] + [
    _fr(k, o, s, 0.0006, 0.0008) - _fr(k, o, s, 0.00036, 0.0010)
    for k, o, s in zip(d.entry_kind, d.outcome, d.sp)
]
d["year"] = d["year"].astype(int)

def stat(sub, col):
    n = len(sub)
    if n < 2:
        return f"n={n}"
    m = sub[col].mean()
    se = sub[col].std(ddof=1) / n ** 0.5
    t = m / se if se and se == se and se != 0 else float("nan")
    return f"n={n:>4} avg={m:+.4f} t={t:+5.2f} Sum={sub[col].sum():+7.1f}"

SYMS = ("SOL", "BTC", "ETH", "BNB", "XRP", "ADA", "DOGE", "KAS", "LTC", "LINK")
out = []
P = out.append

for cfg in ("ABL_MSS_MAIN", "BASE_rerun"):
    q = d[d.config == cfg]
    P(f"===== {cfg} =====")
    P(f"{'пара':>5} | {'ВСЕ ГОДЫ (MEXC)':<42} | 24-26 MEXC | 24-26 Bybit")
    for sym in SYMS:
        g = q[q._sym == sym]
        lt = g[g.year >= 2024]
        P(f"{sym:>5} | {stat(g, 'r_net_mexc'):<42} | {stat(lt, 'r_net_mexc'):<10} | {stat(lt, 'r_byb')}")
    P("")

P("===== ABL_MSS_MAIN по годам 2024/2025/2026 (Bybit) =====")
q = d[d.config == "ABL_MSS_MAIN"]
P(f"{'пара':>5} | {'2024':<26} | {'2025':<26} | {'2026 (до 23.06)':<26}")
for sym in SYMS:
    g = q[q._sym == sym]
    cells = []
    for yr in (2024, 2025, 2026):
        sub = g[g.year == yr]
        if len(sub) < 2:
            cells.append(f"n={len(sub)}")
        else:
            cells.append(f"n={len(sub):>3} avg={sub['r_byb'].mean():+.4f}")
    P(f"{sym:>5} | {cells[0]:<26} | {cells[1]:<26} | {cells[2]:<26}")

txt = "\n".join(out)
print(txt)
open(BASE + "/tf7_pairs_mssmain.txt", "w", encoding="utf-8").write(txt + "\n")

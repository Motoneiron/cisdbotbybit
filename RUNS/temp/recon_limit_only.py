"""LIMIT-only честная база из tp_grid: перепроверка чисел RECON (стоп-сетка, признаки).
tp_grid: строки на каждый hold (6/12/24). r_1.0 = TP1R исход без комиссий.
net по механики бота: tp: r - 2*maker/sp; sl: r - (maker+taker)/sp; time: r - (maker+taker)/sp.
"""
import glob
import pickle

import numpy as np
import pandas as pd

rows = []
for f in sorted(glob.glob("tp_grid/*.pkl")):
    rows.extend(pickle.load(open(f, "rb")))
df = pd.DataFrame(rows)
print("строк:", len(df), "| уникальных сделок:", df.groupby(["sym", "year", "hash"]).ngroups)
print("по hold:", df.hold.value_counts().to_dict())

MAKER, TAKER = 0.00036, 0.0010


def net_r(d):
    sp = d.stop_pct / 100.0
    fee2 = 2 * MAKER / sp
    feem = (MAKER + TAKER) / sp
    r = d["r_1.0"].copy()
    is_tp = d["out_1.0"] == "tp"
    return r - np.where(is_tp, fee2, feem)


for H in (6, 24):
    d = df[df.hold == H].copy()
    d["net"] = net_r(d)
    w = d[d["out_1.0"].isin(["tp", "sl"])]
    wr = 100 * (w["out_1.0"] == "tp").mean()
    sl_share = 100 * (d["out_1.0"] == "sl").mean()
    print(f"\n=== hold {H}ч: n={len(d)} | WR(tp/sl)={wr:.1f}% | SL доля={sl_share:.1f}% | "
          f"Σnet={d.net.sum():.0f} | avg net={d.net.mean():+.3f}")

print("\n=== сетка по ширине стопа (hold 24, как у RECON) ===")
d = df[df.hold == 24].copy()
d["net"] = net_r(d)
print(f"{'отсечка':>8} | {'n':>6} | {'доля SL':>8} | {'net avg':>8} | {'Σnet':>7}")
for thr in (0.0, 1.0, 1.5, 2.0, 3.0):
    g = d[d.stop_pct >= thr] if thr > 0 else d
    print(f"{thr:>7.1f}% | {len(g):>6} | {100*(g['out_1.0']=='sl').mean():>7.1f}% | "
          f"{g.net.mean():>+8.4f} | {g.net.sum():>+7.0f}")

print("\n=== то же на hold 6 (механика бота) ===")
d6 = df[df.hold == 6].copy()
d6["net"] = net_r(d6)
for thr in (0.0, 1.0, 1.5, 2.0):
    g = d6[d6.stop_pct >= thr] if thr > 0 else d6
    print(f"{thr:>7.1f}% | {len(g):>6} | {100*(g['out_1.0']=='sl').mean():>7.1f}% | "
          f"{g.net.mean():>+8.4f} | {g.net.sum():>+7.0f}")

print("\n=== по годам (hold 24, без отсечки) ===")
for y in sorted(d.year.unique()):
    g = d[d.year == y]
    print(f"  {y}: n={len(g):>5} avg={g.net.mean():+.3f} Σ={g.net.sum():+.0f}")

print("\n=== квинтили стопа (hold 24) ===")
d["sq"] = pd.qcut(d.stop_pct, 5, labels=[1, 2, 3, 4, 5])
for q, g in d.groupby("sq", observed=True):
    print(f"  Q{q} (стоп {g.stop_pct.min():.2f}-{g.stop_pct.max():.2f}%): "
          f"SL {100*(g['out_1.0']=='sl').mean():.0f}% | net {g.net.mean():+.4f}")

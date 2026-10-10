"""ema_span_detail2.py — пост-анализ EMA-скрина: sp-бины, направление, годы, пары.

Проверка: не является ли эффект 5m-slope-гейта прокси ширины стопа / направления,
и каков эффект на 2024-26 (боевые годы) и поверх min_stop=1.5%.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

BASE = r"D:/PYTHON/cisdbotbybit/RUNS/temp"
D = pd.read_pickle(f"{BASE}/ema_span_scan_feats.pkl")
print(f"n={len(D)} avg={D.r.mean():+.4f} SR={D.r.sum():+.0f}")

L = (D.direction == "LONG").to_numpy()
S = (D.direction == "SHORT").to_numpy()
V2024 = (D.year == 2024).to_numpy()
V2025 = (D.year == 2025).to_numpy()
V2026 = (D.year == 2026).to_numpy()
SP = D.sp.to_numpy(dtype=float)
R = D.r.to_numpy(dtype=float)

CELLS = [("5m", 5, 0.0002), ("5m", 8, 0.0002), ("5m", 13, 0.0002), ("5m", 21, 0.0002),
         ("5m", 8, 0.0), ("5m", 13, 0.0), ("5m", 13, 0.0005), ("5m", 21, 0.0005)]


def masks(col, thr):
    v = D[col].to_numpy(dtype=float)
    ok = (L & (v > thr)) | (S & (v < -thr)) | np.isnan(v)
    return ok


def avg(m):
    return R[m].mean() if m.any() else float("nan")


def sm(m):
    return R[m].sum() if m.any() else 0.0


print("\n" + "=" * 100)
for tf, span, thr in CELLS:
    col = f"s_{tf}_{span}_incl"
    ok = masks(col, thr)
    skm = ~ok
    psm = ok
    print(f"\n### {tf} span={span} thr={thr*100:.2f}% | skip={100*skm.sum()/len(D):.1f}% skipavg={avg(skm):+.3f} passavg={avg(psm):+.3f}")
    bins = [(0, 0.005), (0.005, 0.01), (0.01, 0.015), (0.015, 0.02), (0.02, 10)]
    print("  sp-бин:      <0.5%   0.5-1%   1-1.5%   1.5-2%     >2%")
    row_sk, row_ps, ns, nps = [], [], [], []
    for lo, hi in bins:
        m = (SP >= lo) & (SP < hi)
        s2 = skm & m
        p2 = psm & m
        row_sk.append(f"{avg(s2):+.3f}" if s2.any() else "   -   ")
        row_ps.append(f"{avg(p2):+.3f}" if p2.any() else "   -   ")
        ns.append(int(s2.sum()))
        nps.append(int(p2.sum()))
    print("  skip_avg:" + "".join(f"{x:>9}" for x in row_sk) + f"   n={ns}")
    print("  pass_avg:" + "".join(f"{x:>9}" for x in row_ps) + f"   n={nps}")
    print("  годы:")
    for tag, msk in (("2024", V2024), ("2025", V2025), ("2026", V2026)):
        s2 = skm & msk
        p2 = psm & msk
        print(f"    {tag}: skip n={int(s2.sum()):>5} avg={avg(s2):+.3f} SR={sm(s2):+7.1f} | pass n={int(p2.sum()):>5} avg={avg(p2):+.3f} SR={sm(p2):+7.1f}")
    for tag, lmask in (("LONG", L), ("SHORT", S)):
        s2 = skm & lmask
        p2 = psm & lmask
        print(f"    {tag:5}: skip n={int(s2.sum()):>5} avg={avg(s2):+.3f} | pass n={int(p2.sum()):>5} avg={avg(p2):+.3f}")
    wide = SP >= 0.015
    s2 = skm & wide
    p2 = psm & wide
    print(f"    sp>=1.5%: skip n={int(s2.sum()):>5} avg={avg(s2):+.3f} | pass n={int(p2.sum()):>5} avg={avg(p2):+.3f}")

print("\n" + "=" * 100)
print("ПО ПАРАМ (5m span=13 thr=0.02%):")
col = "s_5m_13_incl"
ok = masks(col, 0.0002)
skm = ~ok
psm = ok
for sym in sorted(D.sym.unique()):
    mm = (D.sym == sym).to_numpy()
    s2 = skm & mm
    p2 = psm & mm
    print(f"  {sym:5} n={int(mm.sum()):>5} skip%={100*s2.sum()/mm.sum():5.1f} skipavg={avg(s2):+.3f} passavg={avg(p2):+.3f}")

print("\n--- строгий якорь (str), 2024-26 ---")
for tf, span, thr in CELLS[:4] + [("5m", 13, 0.0005)]:
    col = f"s_{tf}_{span}_str"
    ok = masks(col, thr)
    skm = ~ok
    psm = ok
    r24 = skm & (D.year >= 2024).to_numpy()
    p24 = psm & (D.year >= 2024).to_numpy()
    print(f"  {tf} s={span} thr={thr*100:.2f}%: skip n={int(r24.sum())} avg={avg(r24):+.3f} | pass n={int(p24.sum())} avg={avg(p24):+.3f}")
print("\nDONE")

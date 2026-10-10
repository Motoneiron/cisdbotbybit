"""ema_span_detail.py — пост-анализ EMA-скрина: sp-бины, направление, годы, пары.

Проверка: не является ли эффект 5m-slope-гейта прокси ширины стопа / направления,
и каков эффект на 2024-26 (боевые годы) и поверх min_stop=1.5%.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

BASE = r"D:/PYTHON/cisdbotbybit/RUNS/temp"
D = pd.read_pickle(f"{BASE}/ema_span_scan_feats.pkl")
print(f"n={len(D)} avg={D.r.mean():+.4f} SR={D.r.sum():+.0f}")

L = D.direction == "LONG"
S = D.direction == "SHORT"
V2024 = D.year == 2024
V2025 = D.year == 2025
V2026 = D.year == 2026
SP = D.sp

CELLS = [("5m", 5, 0.0002), ("5m", 8, 0.0002), ("5m", 13, 0.0002), ("5m", 21, 0.0002),
         ("5m", 8, 0.0), ("5m", 13, 0.0), ("5m", 13, 0.0005), ("5m", 21, 0.0005)]


def rule_mask(col, thr):
    v = D[col]
    ok = (L & (v > thr)) | (S & (v < -thr)) | v.isna()
    return ok  # True = pass


print("\n" + "=" * 100)
for tf, span, thr in CELLS:
    col = f"s_{tf}_{span}_incl"
    ok = rule_mask(col, thr)
    sk = D[~ok]
    ps = D[ok]
    print(f"\n### {tf} span={span} thr={thr*100:.2f}% | skip={100*len(sk)/len(D):.1f}% skipavg={sk.r.mean():+.3f} passavg={ps.r.mean():+.3f}")
    # 1) sp-бины
    bins = [(0, 0.005), (0.005, 0.01), (0.01, 0.015), (0.015, 0.02), (0.02, 10)]
    print("  sp-бины:  sp<0.5 | 0.5-1.0 | 1.0-1.5 | 1.5-2.0 | >2.0")
    row_sk, row_ps, row_n_sk, row_n_ps = [], [], [], []
    for lo, hi in bins:
        m = (SP >= lo) & (SP < hi)
        s2 = sk & m
        p2 = ps & m
        row_sk.append(f"{s2.r.mean():+.3f}" if len(s2) else "  -  ")
        row_ps.append(f"{p2.r.mean():+.3f}" if len(p2) else "  -  ")
        row_n_sk.append(len(s2))
        row_n_ps.append(len(p2))
    print("  skip_avg: " + " | ".join(f"{x:>7}" for x in row_sk) + "   (n: " + ",".join(map(str, row_n_sk)) + ")")
    print("  pass_avg: " + " | ".join(f"{x:>7}" for x in row_ps) + "   (n: " + ",".join(map(str, row_n_ps)) + ")")
    # 2) годы 2024-26
    print("  годы 24/25/26: ")
    for tag, msk in (("2024", V2024), ("2025", V2025), ("2026", V2026)):
        s2 = sk & msk
        p2 = ps & msk
        print(f"    {tag}: skip n={len(s2):>5} avg={s2.r.mean():+.3f} SR={s2.r.sum():+7.1f} | pass n={len(p2):>5} avg={p2.r.mean():+.3f} SR={p2.r.sum():+7.1f}")
    # 3) направление
    for tag, lmask in (("LONG", L), ("SHORT", S)):
        s2 = sk & lmask
        p2 = ps & lmask
        print(f"    {tag}: skip n={len(s2):>5} avg={s2.r.mean():+.3f} | pass n={len(p2):>5} avg={p2.r.mean():+.3f}")
    # 4) поверх ms1.5: только sp>=1.5%
    wide = SP >= 0.015
    s2 = sk & wide
    p2 = ps & wide
    print(f"    sp>=1.5%: skip n={len(s2):>5} avg={s2.r.mean():+.3f} | pass n={len(p2):>5} avg={p2.r.mean():+.3f}")

print("\n" + "=" * 100)
print("ПО ПАРАМ (5m span=13 thr=0.02%): skip% | skipavg | passavg")
col = "s_5m_13_incl"
ok = rule_mask(col, 0.0002)
sk = D[~ok]
ps = D[ok]
for sym in sorted(D.sym.unique()):
    s2 = sk[sk.sym == sym]
    p2 = ps[ps.sym == sym]
    print(f"  {sym:5} skip%={100*len(s2)/len(D[D.sym==sym]):5.1f} skipavg={s2.r.mean():+.3f} passavg={p2.r.mean():+.3f}")

print("\n--- строгий якорь (str) для тех же клеток, 2024-26 ---")
for tf, span, thr in CELLS[:4] + [("5m", 13, 0.0005)]:
    col = f"s_{tf}_{span}_str"
    ok = rule_mask(col, thr)
    sk = D[~ok]
    ps = D[ok]
    r24 = sk & (D.year >= 2024)
    p24 = ps & (D.year >= 2024)
    print(f"  {tf} span={span} thr={thr*100:.2f}%: skip24-26 n={len(r24)} avg={sk.r.mean():+.3f} | pass24-26 n={len(p24)} avg={ps.r.mean():+.3f}")
print("\nDONE")

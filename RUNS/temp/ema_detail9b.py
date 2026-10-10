"""ema_detail9b.py — чистая база (9 пар, без BTC): ключевые клетки по годам.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

D = pd.read_pickle("ema_span_scan_feats_ETH_DOGE_KAS_ADA_BNB_LINK_LTC_XRP_SOL.pkl")
print(f"n={len(D)} avg={D.r.mean():+.4f}")
L = (D.direction == "LONG").to_numpy()
S = (D.direction == "SHORT").to_numpy()
R = D.r.to_numpy(dtype=float)

CELLS = [("5m", 5, 0.0002), ("5m", 8, 0.0002), ("5m", 13, 0.0002), ("5m", 21, 0.0002),
         ("5m", 5, 0.0), ("5m", 8, 0.0), ("5m", 13, 0.0), ("4h", 8, 0.0002)]

for tf, span, thr in CELLS:
    col = f"s_{tf}_{span}_incl"
    v = D[col].to_numpy(dtype=float)
    ok = (L & (v > thr)) | (S & (v < -thr)) | np.isnan(v)
    skm = ~ok
    psm = ok
    n = len(D)
    sk_avg = R[skm].mean()
    ps_avg = R[psm].mean()
    line = f"\n{tf} s={span} thr={thr*100:.2f}%: skip={100*skm.sum()/n:.1f}% skipavg={sk_avg:+.3f} passavg={ps_avg:+.3f}"
    print(line)
    for y in (2024, 2025, 2026):
        ym = (D.year == y).to_numpy()
        s2 = skm & ym
        p2 = psm & ym
        if s2.any() or p2.any():
            print(f"  {y}: skip n={int(s2.sum()):>4} avg={R[s2].mean() if s2.any() else float('nan'):+.3f} | pass n={int(p2.sum()):>4} avg={R[p2].mean() if p2.any() else float('nan'):+.3f}")
print("\nDONE")

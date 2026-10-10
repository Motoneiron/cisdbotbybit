"""Проверка противоречия: EMA3 1H slope (трендовый фильтр) vs r1h (часовой моментум, который был инверсионным).

Обе меры считаю на ОДНОМ якоре from_ts, по закрытым 1H-бакетам.
Смотрю: корреляцию, согласие знаков, и WR/ΣR по квартилям каждой меры.
"""
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, r"D:/PYTHON")
sys.path.insert(0, r"D:/PYTHON/CISDBOT")
from backtest.data import load_ltf

BASE = r"D:/PYTHON/cisdbotbybit/RUNS/temp"
df = pd.read_pickle(f"{BASE}/stream_ema3.pkl")
df["from_ts"] = pd.to_datetime(df["from_ts"])
df["r1h"] = np.nan
df["r2h"] = np.nan
for sym in sorted(df.sym.unique()):
    d, _ = load_ltf(tf="30m", since="2020-01-01", until="2026-12-31", symbol=sym)
    d.index = pd.DatetimeIndex(d.index)
    h = d["close"].resample("1h", label="left", closed="left").last().dropna()
    idx = df.index[df.sym == sym]
    fts = df.loc[idx, "from_ts"].to_numpy()
    ends = (h.index + pd.Timedelta("1h")).to_numpy()
    i = np.searchsorted(ends, fts, "right") - 1
    good = (i >= 2) & (i < len(h))
    pos = np.clip(np.where(good, i, 0), 0, len(h) - 1)
    c = h.to_numpy(float)
    df.loc[idx, "r1h"] = np.where(good, c[pos] / c[pos - 1] - 1.0, np.nan)
    df.loc[idx, "r2h"] = np.where(good & (pos >= 2), c[pos] / c[pos - 2] - 1.0, np.nan)
    print(f"  [{sym}]", flush=True)
df.to_pickle(f"{BASE}/stream_ema3_r1.pkl")

d = df[df.r1h.notna() & df.slope_h1.notna()].copy()
L = d["dir"] == "LONG"; S = d["dir"] == "SHORT"
print("\n=== корреляции (на from_ts) ===")
print(f"  slope_1h vs r1h : {d.slope_h1.corr(d.r1h):+.3f}")
print(f"  slope_1h vs r2h : {d.slope_h1.corr(d.r2h):+.3f}")
sg = np.sign(d.slope_h1); rg = np.sign(d.r1h)
print(f"  согласие знаков slope_1h и r1h: {100*(sg==rg).mean():.1f}%  (n={len(d)})")


def wr(g):
    x = g[g.outcome.isin(["tp", "sl"])]
    return 100.0 * (x.outcome == "tp").mean() if len(x) else float("nan")


print("\n=== квартили r1h: направленная ставка (лонг если r1h>0, шорт если <0) vs инверсия ===")
d["q_r1"] = pd.qcut(d.r1h, 5, labels=False, duplicates="drop")
for q, g in d.groupby("q_r1"):
    tr = g[g["dir"] == "LONG"]
    print(f"  q{int(q)}: r1h {g.r1h.min()*100:+.2f}%..{g.r1h.max()*100:+.2f}% | n={len(g):5d} WR={wr(g):.1f}% ΣR={g.r_net.sum():+8.1f}")

print("\n=== квартили slope_1h ===")
d["q_sl"] = pd.qcut(d.slope_h1, 5, labels=False, duplicates="drop")
for q, g in d.groupby("q_sl"):
    print(f"  q{int(q)}: slope {g.slope_h1.min()*100:+.3f}%..{g.slope_h1.max()*100:+.3f}% | n={len(g):5d} WR={wr(g):.1f}% ΣR={g.r_net.sum():+8.1f}")

print("\n=== ЧЕСТНАЯ проверка: направление сделки ПРОТИВ/ПО наклону (на from_ts) ===")
same_r1 = ((L & (d.r1h > 0)) | (S & (d.r1h < 0)))
same_sl = ((L & (d.slope_h1 > 0)) | (S & (d.slope_h1 < 0)))
for lab, m in [("r1h: по тренду", same_r1), ("r1h: против тренда", ~same_r1 & ~d.r1h.isna()),
               ("slope1h: по тренду", same_sl), ("slope1h: против тренда", ~same_sl)]:
    g = d[m.fillna(False)]
    print(f"  {lab:22} n={len(g):5d} WR={wr(g):.1f}% avg={g.r_net.mean():+.4f} ΣR={g.r_net.sum():+8.1f}")

print("\n=== то же по подписанной мере: for long reward r1h>0 (моментум), для шорта r1h<0 ===")
d["signed_r1"] = np.where(d["dir"] == "LONG", d.r1h, -d.r1h)
d["signed_sl"] = np.where(d["dir"] == "LONG", d.slope_h1, -d.slope_h1)
for c in ("signed_r1", "signed_sl"):
    d["q"] = pd.qcut(d[c], 5, labels=False, duplicates="drop")
    print(f"  --- {c} (положительное = «в сторону сделки») ---")
    for q, g in d.groupby("q"):
        print(f"     q{int(q)}: {g[c].min()*100:+.3f}%..{g[c].max()*100:+.3f}% n={len(g):5d} WR={wr(g):.1f}% avg={g.r_net.mean():+.4f} ΣR={g.r_net.sum():+8.1f}")
print("\nDONE")

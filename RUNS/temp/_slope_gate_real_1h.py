"""Поток 2020–26: настоящий EMA3 по 1H-закрытиям (не 30m-прокси).

Источник сделок: stream_ungated_v2.csv, только tf8.
slope = (EMA3(close_1h)[i]/EMA3[i-1]-1) по барам с close_time < from_ts.
"""
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, r"D:/PYTHON")
sys.path.insert(0, r"D:/PYTHON/CISDBOT")
from backtest.data import load_ltf  # noqa: E402

BASE = r"D:/PYTHON/cisdbotbybit/RUNS/temp"
THR = 0.0002  # 0.02% как доля
MIN_STOP = 0.0025
df = pd.read_csv(f"{BASE}/stream_ungated_v2.csv")
df = df[df["prof"].astype(str) == "tf8"].copy()
df["from_ts"] = pd.to_datetime(df["from_ts"])
if "sp" in df.columns:
    df = df[df["sp"].astype(float) >= MIN_STOP].copy()
df["slope_1h"] = np.nan

for sym in sorted(df.sym.unique()):
    d30, _ = load_ltf(tf="30m", since="2020-01-01", until="2026-12-31", symbol=sym)
    d30.index = pd.DatetimeIndex(d30.index)
    h = pd.DataFrame(
        {"close": d30["close"].resample("1h", label="left", closed="left").last()}
    ).dropna()
    e3 = h["close"].ewm(span=3, adjust=False).mean()
    sl = (e3 / e3.shift(1) - 1.0)
    ends = (h.index + pd.Timedelta("1h")).to_numpy()
    idx = df.index[df.sym == sym]
    fts = df.loc[idx, "from_ts"].to_numpy()
    i = np.searchsorted(ends, fts, side="left") - 1
    good = (i >= 2) & (i < len(h))
    pos = np.clip(np.where(good, i, 0), 0, len(h) - 1)
    sa = sl.to_numpy(dtype=float)
    df.loc[idx, "slope_1h"] = np.where(good, sa[pos], np.nan)
    print(f"  [{sym}] n={int(good.sum())}/{len(idx)}", flush=True)

df = df[np.isfinite(df.slope_1h)].copy()
L = df["dir"] == "LONG"
S = df["dir"] == "SHORT"
with_m = (L & (df.slope_1h > THR)) | (S & (df.slope_1h < -THR))
dead = df.slope_1h.abs() < THR
# гейт режет: не WITH и не dead (как _slope_filter_ok_hermes при th>0)
ok = with_m | dead
cut = ~ok
rcol = "r_net"
year = df["year"] if "year" in df.columns else df["from_ts"].dt.year


def wr(g):
    d = g[g["outcome"].isin(["tp", "sl"])] if "outcome" in g.columns else g
    if "outcome" not in g.columns or len(d) == 0:
        return float("nan")
    return 100.0 * (d["outcome"] == "tp").mean()


print()
print(f"tf8 сделок с наклоном: {len(df)}")
print()


def st(name, g):
    if not len(g):
        print(f"  {name:32s}: --")
        return
    w = wr(g)
    wr_s = f"WR={w:5.1f}%" if np.isfinite(w) else "WR=  n/a"
    print(
        f"  {name:32s}: n={len(g):6d} ({100 * len(g) / len(df):4.1f}%) "
        f"{wr_s} SR={g[rcol].sum():+9.1f} avg={g[rcol].mean():+.3f}"
    )


st("all", df)
st("gate PASS (WITH+flat)", df[ok])
st("gate SKIP (against)", df[cut])
st("dead zone |slope|<0.02%", df[dead])
st("research AGAINST (not WITH)", df[~with_m])
print()
print("AGAINST (gate SKIP) by year:")
bad = []
for y, g in df.groupby(year):
    a = g.loc[cut.reindex(g.index).fillna(False)]
    w = g.loc[ok.reindex(g.index).fillna(False)]
    s = float(a[rcol].sum()) if len(a) else 0.0
    print(
        f"  {int(y)}: SKIP n={len(a):5d} SR={s:+8.1f} | PASS n={len(w):5d} "
        f"SR={w[rcol].sum():+8.1f}"
    )
    if s >= 0 and len(a) > 0:
        bad.append(int(y))
print()
share = 100 * cut.mean()
sr_cut = float(df.loc[cut, rcol].sum())
print(f"SKIP share={share:.1f}%  SKIP SR={sr_cut:+.1f}")
if bad:
    print("STOP: SKIP nonnegative in years:", bad)
else:
    print("OK: SKIP negative every year")
df.to_pickle(f"{BASE}/stream_slope_gate_real1h.pkl")
print("saved stream_slope_gate_real1h.pkl")

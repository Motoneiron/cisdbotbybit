# -*- coding: utf-8 -*-
"""Воронка отсечения: фильтры A/V/D бота + vwap-гейт vs формула — на голом SOL-потоке.

Досчитывает vol на trigger-баре и soft-флаг (из сигналов), строит каскад:
  все -> [A для tf7] -> [V/D матрица для tf7] -> [гейт vd_conf] 
и сравнение с формулой: резы по p_short4/base11 (квантильные + равномощный гейту рез).
Только чтение чужих файлов.
"""
from __future__ import annotations

import pickle
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, r"D:/PYTHON")
sys.path.insert(0, r"D:/PYTHON/CISDBOT")

from backtest.data import load_ltf
from backtest.touch_filter import is_soft_dow
from backtest.volume_filter import volume_ratio_series

BASE = r"D:/PYTHON/cisdbotbybit/RUNS/temp"
CDIR = r"D:/PYTHON/CISDBOT/RUNS/filters_off_full"
WINDOW = 200
SW_MIN = 0.40
VOL_MAX = 2.5
TOUCH_MIN = 5


def trig_global(scan_bar, trigger_idx, n):
    gi = max(0, int(scan_bar) - (WINDOW - 1)) + int(trigger_idx)
    return gi if 0 <= gi < n else None


def wr(g):
    d = g[g.outcome.isin(["tp", "sl"])]
    return 100.0 * (d.outcome == "tp").mean() if len(d) else float("nan")


def line(label, g):
    return (f"  {label:44}: n={len(g):5d} ({100*len(g)/N0:5.1f}%) WR={wr(g):5.1f}% "
            f"ΣR={g.r_net.sum():+8.1f} avgR={g.r_net.mean():+.3f}")


df = pd.read_pickle(f"{BASE}/lr18_ungated_pred.pkl").reset_index(drop=True)
N0 = len(df)
df["vol_trig"] = np.nan
df["soft"] = np.nan

print(f"голый SOL: {N0} сделок", flush=True)
for (prof, year), idx in df.groupby(["prof", "year"]).groups.items():
    idx = pd.Index(idx)
    with open(f"{CDIR}/SOL_{prof}_{year}-01-01_{year}-12-31.pkl", "rb") as fh:
        c = pickle.load(fh)
    sigs = {str(s.get("hash")): s for s in c.get("signals") or []}
    tf = "5m" if prof == "tf7" else "30m"
    dft, _ = load_ltf(tf=tf, since=f"{int(year)}-01-01", until=f"{int(year)}-12-31", symbol="SOL")
    dft.index = pd.DatetimeIndex(dft.index)
    n = len(dft)
    vr = volume_ratio_series(dft, 20).to_numpy(float)
    for row_i, hsh in zip(idx, df.loc[idx, "hash"].astype(str)):
        s = sigs.get(hsh)
        if not s:
            continue
        gi = trig_global(s.get("scan_bar"), s.get("trigger_idx"), n)
        if gi is not None and pd.notna(vr[gi]):
            df.at[row_i, "vol_trig"] = float(vr[gi])
        tb = s.get("trigger_bar_time")
        df.at[row_i, "soft"] = 1.0 if is_soft_dow(pd.Timestamp(str(tb))) else 0.0
    print(f"  [{prof} {int(year)}] ok", flush=True)

df.to_pickle(f"{BASE}/lr18_ungated_funnel.pkl")

S = df["dir"] == "SHORT"; L = df["dir"] == "LONG"
gate = (S & (df.vd_conf <= 0)) | (L & (df.vd_conf >= 0))
tf7 = df.prof == "tf7"
soft = df["soft"] == 1.0
A = (df.sweep_atr >= SW_MIN).fillna(False)
VD = np.where(soft, df.prior_touches >= TOUCH_MIN, df.vol_trig <= VOL_MAX)
VD = pd.Series(VD, index=df.index).fillna(False)
AVD = A & VD
AVD_ok = tf7 & AVD | (~tf7)  # tf8: фильтры выключены в текущем каноне

print("\n=========== ВОРОНКА (каскад как в боте: фильтры -> гейт) ===========", flush=True)
print(line("0. все сделки (голый поток)", df), flush=True)
print(line("1. после A (sweep/ATR>=0.40, только tf7)", df[tf7 & A | (~tf7)]), flush=True)
print(line("2. после V/D-матрицы (tf7)", df[AVD_ok]), flush=True)
print(line("3. после фильтров + гейт vd_conf (боевой)", df[AVD_ok & gate]), flush=True)
print("\n--- отдельно слоями (для масштаба) ---", flush=True)
print(line("гейт ТОЛЬКО (без фильтров)", df[gate]), flush=True)
print(line("tf7: фильтры A+V/D", df[tf7 & AVD]), flush=True)
print(line("tf8: без фильтров (канон)", df[~tf7]), flush=True)

print("\n--- по профилям: воронка ---", flush=True)
for p in ("tf7", "tf8"):
    d = df[df.prof == p]
    print(f"  == {p} ({len(d)}) ==", flush=True)
    if p == "tf7":
        print(f"    после A:        {int((A[d.index]).sum()):5d}  ({100*(A[d.index]).mean():.1f}%)", flush=True)
        print(f"    после A+V/D:    {int((A[d.index] & VD[d.index]).sum()):5d}  ({100*(A[d.index] & VD[d.index]).mean():.1f}%)", flush=True)
        print(f"    после + гейт:   {int((A[d.index] & VD[d.index] & gate[d.index]).sum()):5d}  ({100*(A[d.index] & VD[d.index] & gate[d.index]).mean():.1f}%)", flush=True)
    else:
        print(f"    гейт:           {int((gate[d.index]).sum()):5d}  ({100*(gate[d.index]).mean():.1f}%)", flush=True)

print("\n=========== ФОРМУЛА КАК ОТСЕКАТЕЛЬ (p_short4, голый поток) ===========", flush=True)
ok = df.outcome.isin(["tp", "sl"]) & df.p_short4.notna()
d = df[ok].copy()
for q in (0.10, 0.20, 0.33, 0.50):
    cut = d.p_short4.quantile(q)
    drop = d[d.p_short4 <= cut]; keep = d[d.p_short4 > cut]
    print(f"  резать нижние {int(q*100):2d}% (p<{cut:.3f}): уходит {len(drop):4d} сд "
          f"(ΣR {drop.r_net.sum():+7.1f}, avgR {drop.r_net.mean():+.3f}) | остаток: n={len(keep)} "
          f"WR={wr(keep):.1f}% ΣR={keep.r_net.sum():+7.1f} avgR={keep.r_net.mean():+.3f}", flush=True)

# равномощный рез: столько же, сколько режет гейт
gate_share = gate[df.outcome.isin(['tp','sl']) & df.p_short4.notna()].mean()
q_eq = 1.0 - gate_share
cut = d.p_short4.quantile(q_eq)
drop = d[d.p_short4 <= cut]; keep = d[d.p_short4 > cut]
print(f"\n  равномощно гейту (аналог {100*q_eq:.1f}% остатка): резать {100*(1-q_eq):.1f}% "
      f"(p<{cut:.3f}): уходит {len(drop)} (avgR {drop.r_net.mean():+.3f}) | "
      f"остаток n={len(keep)} WR={wr(keep):.1f}% ΣR={keep.r_net.sum():+.1f} avgR={keep.r_net.mean():+.3f}", flush=True)
# для сравнения: остаток гейта на тех же tp/sl
g_keep = df[ok & gate]
print(f"  [сравн.] гейт-остаток: n={len(g_keep)} WR={wr(g_keep):.1f}% ΣR={g_keep.r_net.sum():+.1f} avgR={g_keep.r_net.mean():+.3f}", flush=True)
print("\nDONE", flush=True)

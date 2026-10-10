"""Тайм-аут выхода tf8: переманим ли TIME в TP?

1) Горизонты 6/9/12/18/24/36/48ч: TP/SL/TIME, WR, ΣR (TP=1R, те же комиссии, что в потоке).
2) Переход: чем становятся сделки, закрытые по TIME на 6ч, если держать дольше + сколько времени им нужно.
3) Динамический таймаут: конверсия TIME→TP и ΔΣR по часу входа (UTC) и дню недели + проверка на двух половинах истории.
"""
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, r"D:/PYTHON")
sys.path.insert(0, r"D:/PYTHON/CISDBOT")
from backtest.data import load_ltf

BASE = r"D:/PYTHON/cisdbotbybit/RUNS/temp"
MAKER, TAKER = 0.00036, 0.0010
HS = [6, 9, 12, 18, 24, 36, 48]
PROF = "tf8"

df = pd.read_pickle(f"{BASE}/stream_ema3.pkl")
df = df[df.prof == PROF].copy()
df["ts_fill"] = pd.to_datetime(df.ts_fill)
df = df[df["dir"].notna()].copy()
for h in HS:
    df[f"res_{h}"] = None
    df[f"r_{h}"] = np.nan
df["t_tp_min"] = np.nan
df["t_sl_min"] = np.nan
df["res_far"] = None

for (sym, year), idx in df.groupby(["sym", "year"]).groups.items():
    try:
        d1, _ = load_ltf(tf="1m", since=f"{int(year)}-01-01", until=f"{int(year)}-12-31", symbol=sym)
    except Exception as e:
        print(f"  load fail {sym} {year}: {e!r}", flush=True); continue
    d1.index = pd.DatetimeIndex(d1.index)
    ts = d1.index.to_numpy()
    hi = d1["high"].to_numpy(float); lo = d1["low"].to_numpy(float); cl = d1["close"].to_numpy(float)
    for r_i, row in df.loc[idx].iterrows():
        t0 = np.datetime64(row.ts_fill)
        tmax = t0 + np.timedelta64(48, "h")
        a = int(np.searchsorted(ts, t0, "left")); b = int(np.searchsorted(ts, tmax, "right"))
        if b - a < 2:
            continue
        H = hi[a:b]; L = lo[a:b]
        entry, stop = float(row.entry), float(row.stop)
        long = row["dir"] == "LONG"
        sp = abs(entry - stop) / entry
        if sp <= 0:
            continue
        tp_pr = entry + (entry - stop) if long else entry - (stop - entry)
        if long:
            hit_tp = L <= stop; hit_tp2 = H >= tp_pr
        else:
            hit_tp = H >= stop; hit_tp2 = L <= tp_pr
        i_sl = int(np.argmax(hit_tp)) if hit_tp.any() else 10**9
        i_tp = int(np.argmax(hit_tp2)) if hit_tp2.any() else 10**9
        if i_tp < 10**9:
            df.at[r_i, "t_tp_min"] = i_tp
        if i_sl < 10**9:
            df.at[r_i, "t_sl_min"] = i_sl
        for h in HS:
            nb = int(np.searchsorted(ts, t0 + np.timedelta64(h, "h"), "right")) - a
            if nb <= 0:
                continue
            if i_sl < 10**9 and (i_tp >= 10**9 or i_sl <= i_tp) and i_sl < nb:
                r, res = -1.0 - MAKER / sp - TAKER / sp, "sl"
            elif i_tp < 10**9 and i_tp < nb:
                r, res = 1.0 - 2 * MAKER / sp, "tp"
            else:
                px = cl[a + nb - 1]
                risk = (entry - stop) if long else (stop - entry)
                r = (((px - entry) if long else (entry - px)) / risk) - MAKER / sp - TAKER / sp
                res = "time"
            df.at[r_i, f"r_{h}"] = r
            df.at[r_i, f"res_{h}"] = res
        # далёкий исход (48ч) для разбора TIME
        if i_sl < 10**9 and (i_tp >= 10**9 or i_sl <= i_tp):
            df.at[r_i, "res_far"] = "sl"
        elif i_tp < 10**9:
            df.at[r_i, "res_far"] = "tp"
        else:
            df.at[r_i, "res_far"] = "time"
    print(f"  [{sym} {year}] ok", flush=True)
df.to_pickle(f"{BASE}/stream_tf8_timeout.pkl")

ok = df["r_6"].notna()
print(f"\nпокрытие: {int(ok.sum())} из {len(df)}")
d = df[ok].copy()
print(f"\n=== tf8: горизонты удержания (TP=1R, комиссии Bybit) ===")
print(f"  {'часы':>5} | {'TP':>6} {'SL':>6} {'TIME':>6} | {'WR':>6} | {'ΣR':>9} {'avg':>8}")
for h in HS:
    g = d[d[f"res_{h}"].notna()]
    tp = (g[f"res_{h}"] == "tp").sum(); sl = (g[f"res_{h}"] == "sl").sum(); tm = (g[f"res_{h}"] == "time").sum()
    print(f"  {h:5d} | {tp:6d} {sl:6d} {tm:6d} | {100*tp/max(1,tp+sl):5.1f}% | {g[f'r_{h}'].sum():+9.1f} {g[f'r_{h}'].mean():+8.4f}")

cur = d[d["res_6"] == "time"]
print(f"\n=== ЧТО СТАНОВИТСЯ С TIME-СДЕЛКАМИ (сейчас их {len(cur)}, 6ч) ===")
for h in HS[1:]:
    g = cur[cur[f"res_{h}"].notna()]
    tp = (g[f"res_{h}"] == "tp").sum(); sl = (g[f"res_{h}"] == "sl").sum(); tm = (g[f"res_{h}"] == "time").sum()
    print(f"  держим до {h:2d}ч: TP {tp:5d} ({100*tp/len(g):4.1f}%) | SL {sl:5d} ({100*sl/len(g):4.1f}%) | всё ещё TIME {tm:5d} "
          f"| ΔΣR к текущему {g[f'r_{h}'].sum() - g['r_6'].sum():+8.1f}")
tt = cur[cur.t_tp_min.notna()].t_tp_min / 60.0
print(f"\n  время до TP у тех, кто дотянет: медиана {tt.median():.1f}ч, p75 {tt.quantile(.75):.1f}ч, p90 {tt.quantile(.9):.1f}ч (n={len(tt)})")
print(f"  сколько конверсий произойдёт после 6ч: до 9ч {100*(tt<=9).mean():.0f}%, до 12ч {100*(tt<=12).mean():.0f}%, до 24ч {100*(tt<=24).mean():.0f}%")

print(f"\n=== ΔΣR по годам: 6ч → 12ч / 24ч / 48ч ===")
for y, g in d.groupby("year"):
    print(f"  {int(y)}: 6ч {g['r_6'].sum():+7.1f} | 12ч {g['r_12'].sum():+7.1f} (Δ{g['r_12'].sum()-g['r_6'].sum():+7.1f})"
          f" | 24ч {g['r_24'].sum():+7.1f} (Δ{g['r_24'].sum()-g['r_6'].sum():+7.1f})"
          f" | 48ч {g['r_48'].sum():+7.1f} (Δ{g['r_48'].sum()-g['r_6'].sum():+7.1f})")

d["hod"] = d.ts_fill.dt.hour
print("\n=== Динамический таймаут: эффект продления 6ч→24ч по ЧАСУ ВХОДА (UTC) ===")
print(f"  {'час':>4} | {'сделок':>7} {'TIME@6ч':>8} {'из них TP@24ч':>13} | {'ΔΣR(6→24)':>10}")
for hod, g in d.groupby("hod"):
    t6 = g[g["res_6"] == "time"]
    conv = (t6["res_24"] == "tp").sum() if len(t6) else 0
    print(f"  {hod:4d} | {len(g):7d} {len(t6):8d} {conv:8d} ({100*conv/max(1,len(t6)):4.0f}%) | {g['r_24'].sum()-g['r_6'].sum():+10.1f}")

d["dow"] = d.ts_fill.dt.dayofweek
print("\n=== то же по ДНЮ НЕДЕЛИ (0=Пн) ===")
for dow, g in d.groupby("dow"):
    t6 = g[g["res_6"] == "time"]
    conv = (t6["res_24"] == "tp").sum() if len(t6) else 0
    print(f"  {dow:4d} | {len(g):7d} {len(t6):8d} {conv:8d} ({100*conv/max(1,len(t6)):4.0f}%) | {g['r_24'].sum()-g['r_6'].sum():+10.1f}")

print("\n=== устойчивость: половинки истории (по часу входа, ΔΣR 6→24) ===")
half = d.ts_fill < d.ts_fill.quantile(0.5)
for nm, sub in (("первая половина", d[half]), ("вторая половина", d[~half])):
    top = (sub.groupby("hod").apply(lambda g: g["r_24"].sum() - g["r_6"].sum())).sort_values(ascending=False)[:4]
    bot = (sub.groupby("hod").apply(lambda g: g["r_24"].sum() - g["r_6"].sum())).sort_values()[:4]
    print(f"  {nm}: лучшие часы {[int(i) for i in top.index]} → {[round(v,0) for v in top.values]}")
    print(f"  {'':16} худшие часы {[int(i) for i in bot.index]} → {[round(v,0) for v in bot.values]}")
print("\nDONE")

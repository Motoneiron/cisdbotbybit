"""Адаптивный TP при узком стопе: TP = 1R по умолчанию, TP = 1.5R если стоп узкий.

Идея пользователя: при sp=0.27% SL стоит −1.5R (комиссии) — значит тейк должен быть больше.
Симулируем на 1m (честно, как в потоке): для каждого уровня TP ищем первое касание SL/TP.
Комиссии Bybit: TP (maker) = x − 2*maker/sp; SL = −1 − (maker+taker)/sp.

САНITY: вариант X=1.0 должен воспроизвести r_net потока.
"""
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, r"D:/PYTHON")
sys.path.insert(0, r"D:/PYTHON/CISDBOT")
from backtest.data import load_ltf

BASE = r"D:/PYTHON/cisdbotbybit/RUNS/temp"
MAKER, TAKER = 0.00036, 0.0010
POSH = {"tf7": 16, "tf8": 6}
XS = (1.0, 1.25, 1.5, 2.0)


def wr(g):
    d = g[g.outcome.isin(["tp", "sl"])]
    return 100.0 * (d.outcome == "tp").mean() if len(d) else float("nan")


df = pd.read_pickle(f"{BASE}/stream_reanchor_full.pkl").copy()
df["from_ts"] = pd.to_datetime(df["from_ts"])
df["ts_fill"] = pd.to_datetime(df["ts_fill"])
for x in XS:
    df[f"r_{x}".replace(".", "_")] = np.nan
    df[f"res_{x}".replace(".", "_")] = None

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
        ph = POSH[row.prof]
        t1 = t0 + np.timedelta64(ph, "h")
        a = int(np.searchsorted(ts, t0, "left"))
        b = int(np.searchsorted(ts, t1, "right"))
        if b <= a:
            continue
        H = hi[a:b]; L = lo[a:b]
        entry, stop = float(row.entry), float(row.stop)
        long = row["dir"] == "LONG"
        sp = abs(entry - stop) / entry
        if sp <= 0:
            continue
        for x in XS:
            tpx = entry + x * (entry - stop) if long else entry - x * (stop - entry)
            if long:
                i_sl = np.argmax(L <= stop) if (L <= stop).any() else 10**9
                i_tp = np.argmax(H >= tpx) if (H >= tpx).any() else 10**9
            else:
                i_sl = np.argmax(H >= stop) if (H >= stop).any() else 10**9
                i_tp = np.argmax(L <= tpx) if (L <= tpx).any() else 10**9
            if i_sl == i_tp == 10**9:
                px = cl[b - 1]
                risk = (entry - stop) if long else (stop - entry)
                r = (((px - entry) if long else (entry - px)) / risk) - MAKER / sp - TAKER / sp
                res = "time"
            elif i_sl <= i_tp:
                r, res = -1.0 - MAKER / sp - TAKER / sp, "sl"
            else:
                r, res = x - 2 * MAKER / sp, "tp"
            df.at[r_i, f"r_{x}".replace(".", "_")] = r
            df.at[r_i, f"res_{x}".replace(".", "_")] = res
    print(f"  [{sym} {year}] ok", flush=True)

df.to_pickle(f"{BASE}/stream_tp_grid.pkl")
ok = df.r_1_0.notna()
print(f"\nсимуляция покрыла {int(ok.sum())} из {len(df)}", flush=True)
print("\n=== SANITY: X=1.0 против потока ===", flush=True)
d = df[ok & df.r_net.notna()]
print(f"  корр: {np.corrcoef(d.r_1_0, d.r_net)[0,1]:.4f} | медиана |разн|: {(d.r_1_0-d.r_net).abs().median():.5f} | "
      f"Σ simul {d.r_1_0.sum():+.1f} vs поток {d.r_net.sum():+.1f}", flush=True)

print("\n=== TP-варианты (весь поток) ===", flush=True)
for x in XS:
    g = df[df[f"r_{x}".replace(".", "_")].notna()]
    tp = (g[f"res_{x}"] == "tp").sum(); sl = (g[f"res_{x}"] == "sl").sum()
    print(f"  TP={x}R: n={len(g)} WR={100*tp/max(1,tp+sl):.1f}% ΣR={g[f"r_{x}".replace(".", "_")].sum():+8.1f} avg={g[f"r_{x}".replace(".", "_")].mean():+.3f}", flush=True)

print("\n=== АДАПТИВНО: TP=1.5R если sp < порога, иначе 1R ===", flush=True)
for thr in (0.004, 0.005, 0.006, 0.008, 0.010):
    g = df[df.r_1_0.notna()].copy()
    nar = g.sp < thr
    g["r_ad"] = np.where(nar, g.r_1_5, g.r_1_0)
    g["res_ad"] = np.where(nar, g.res_1_5, g.res_1_0)
    tp = (g.res_ad == "tp").sum(); sl = (g.res_ad == "sl").sum()
    print(f"  sp<{100*thr:.1f}% (n узких {int(nar.sum())}): WR={100*tp/max(1,tp+sl):.1f}% ΣR={g.r_ad.sum():+8.1f} avg={g.r_ad.mean():+.3f} "
          f"(база TP1R: {g.r_1_0.sum():+.1f})", flush=True)

print("\n=== то же по годам (лучший порог 0.5%) ===", flush=True)
g = df[df.r_1_0.notna()].copy()
nar = g.sp < 0.005
g["r_ad"] = np.where(nar, g.r_1_5, g.r_1_0)
for y, gg in g.groupby("year"):
    print(f"  {int(y)}: база {gg.r_1_0.sum():+7.1f} | адаптив {gg.r_ad.sum():+7.1f} | Δ {gg.r_ad.sum()-gg.r_1_0.sum():+7.1f}", flush=True)

print("\n=== узкие стопы отдельно (sp<0.5%): что делает TP1R vs TP1.5R ===", flush=True)
n = df[df.r_1_0.notna() & (df.sp < 0.005)]
for x in XS:
    tp = (n[f"res_{x}"] == "tp").sum(); sl = (n[f"res_{x}"] == "sl").sum()
    print(f"  TP={x}R: n={len(n)} TP/SL/TIME={tp}/{sl}/{int((n[f"res_{x}".replace(".", "_")]=='time').sum())} WR={100*tp/max(1,tp+sl):.1f}% "
          f"ΣR={n[f'r_{x}'].sum():+8.1f} avg={n[f'r_{x}'].mean():+.3f}", flush=True)
print("\nDONE", flush=True)

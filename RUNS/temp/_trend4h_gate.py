"""4H-трендовый гейт: лонги только выше 4H-EMA20/EMA50 (и вариант с наклоном), шорты — ниже.

Считаем на живом якоре (from_ts), разбивка по годам + OOS 2024-26 + портфель.
"""
import heapq
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, r"D:/PYTHON")
sys.path.insert(0, r"D:/PYTHON/CISDBOT")
from backtest.data import load_ltf

BASE = r"D:/PYTHON/cisdbotbybit/RUNS/temp"


def wr(g):
    d = g[g.outcome.isin(["tp", "sl"])]
    return 100.0 * (d.outcome == "tp").mean() if len(d) else float("nan")


def main():
    df = pd.read_pickle(f"{BASE}/stream_regime_live.pkl").copy()
    df["from_ts"] = pd.to_datetime(df["from_ts"])
    for c in ("t4_e20", "t4_e50", "t4_slope"):
        df[c] = np.nan
    for sym in sorted(df.sym.unique()):
        try:
            d30, _ = load_ltf(tf="30m", since="2020-01-01", until="2026-12-31", symbol=sym)
        except Exception as e:
            print(f"  load fail {sym}: {e!r}", flush=True); continue
        d30.index = pd.DatetimeIndex(d30.index)
        h = pd.DataFrame({"close": d30["close"].resample("4h", label="left", closed="left").last()}).dropna()
        h["e20"] = h["close"].ewm(span=20, adjust=False, min_periods=20).mean()
        h["e50"] = h["close"].ewm(span=50, adjust=False, min_periods=50).mean()
        h["slope"] = h["e20"] / h["e20"].shift(3) - 1.0
        idx = df.index[df.sym == sym]
        fts = df.loc[idx, "from_ts"].to_numpy()
        i = np.searchsorted(h.index.to_numpy() + np.timedelta64(4, "h"), fts, "right") - 1
        good = (i >= 50) & (i < len(h))
        pos = np.clip(np.where(good, i, 0), 0, len(h) - 1)
        cl = h["close"].to_numpy(float); e20 = h["e20"].to_numpy(float)
        e50 = h["e50"].to_numpy(float); sl = h["slope"].to_numpy(float)
        df.loc[idx, "t4_e20"] = np.where(good, cl[pos] / e20[pos] - 1.0, np.nan)
        df.loc[idx, "t4_e50"] = np.where(good, cl[pos] / e50[pos] - 1.0, np.nan)
        df.loc[idx, "t4_slope"] = np.where(good, sl[pos], np.nan)
        print(f"  [{sym}] ok ({len(idx)} строк)", flush=True)
    df.to_pickle(f"{BASE}/stream_trend4h.pkl")

    L = df["dir"] == "LONG"; S = df["dir"] == "SHORT"
    print("\n=== ЛОНГИ по 4H-тренду (close vs EMA20) ===", flush=True)
    print("  по годам: above / below  (ΣR, n)", flush=True)
    for y, g in df.groupby("year"):
        l = g[g["dir"] == "LONG"]
        a = l[l.t4_e20 > 0]; b = l[l.t4_e20 <= 0]
        print(f"    {int(y)}: выше {a.r_net.sum():+7.1f} (n={len(a):5d}) | ниже {b.r_net.sum():+7.1f} (n={len(b):5d})", flush=True)
    print("\n=== ШОРТЫ по 4H-тренду ===", flush=True)
    for y, g in df.groupby("year"):
        s = g[g["dir"] == "SHORT"]
        a = s[s.t4_e20 < 0]; b = s[s.t4_e20 >= 0]
        print(f"    {int(y)}: ниже {a.r_net.sum():+7.1f} | выше {b.r_net.sum():+7.1f}", flush=True)

    RULES = {
        "raw": pd.Series(True, index=df.index),
        "ДЕПЛОЙ vwap": (S & (df.vd_conf <= 0)) | (L & (df.vd_conf >= 0)),
        "ТРЕНД ДН (L>EMA50д)": (L & (df.trend > 0)) | (S & (df.trend < 0)),
        "ТРЕНД 4H (L>E20/S<E20)": (L & (df.t4_e20 > 0)) | (S & (df.t4_e20 < 0)),
        "L>E20_4H, шорты все": (L & (df.t4_e20 > 0)) | S,
        "L>E20_4H & vd>=0 / S все": (L & (df.t4_e20 > 0) & (df.vd_conf >= 0)) | S,
        "L>E20_4H & slope>0 / S все": (L & (df.t4_e20 > 0) & (df.t4_slope > 0)) | S,
    }
    print("\n=== СУММЫ: весь период / 2024-26 ===", flush=True)
    for n, m in RULES.items():
        g = df[m.fillna(False)]; g4 = g[g.year >= 2024]
        print(f"  {n:26} | весь n={len(g):6d} WR={wr(g):5.1f}% ΣR={g.r_net.sum():+8.1f} | "
              f"2024-26 n={len(g4):5d} WR={wr(g4):5.1f}% ΣR={g4.r_net.sum():+8.1f}", flush=True)

    def portfolio(d, risk=0.01, start=100.0, max_pos=7):
        d = d.sort_values("t_in")
        items = list(zip(d.t_in.astype("int64"), d.t_out.astype("int64"), d.sym, d.r_net.astype(float)))
        pe, heap, taken = {}, [], []
        for tin, tout, sym, r in items:
            while heap and heap[0] <= tin:
                heapq.heappop(heap)
            p = pe.get(sym)
            if p is not None and tin < p:
                continue
            if len(heap) >= max_pos:
                continue
            taken.append((tin, tout, r)); heapq.heappush(heap, tout); pe[sym] = tout
        ev = []
        for i, (tin, tout, r) in enumerate(taken):
            ev.append((tin, 1, i)); ev.append((tout, 0, i))
        ev.sort(key=lambda e: (e[0], e[1], e[2]))
        bal = start; rm = {}; curve = [(ev[0][0] if ev else 0, bal)]
        for t, k, i in ev:
            tin, tout, r = taken[i]
            if k == 0:
                if i in rm:
                    bal += rm.pop(i) * r
            else:
                if tout <= tin:
                    bal += bal * risk * r
                else:
                    rm[i] = bal * risk
            curve.append((t, bal))
        s = pd.Series([c[1] for c in curve])
        return bal, float(((s - s.cummax()) / s.cummax()).min() * 100), len(taken)

    df["t_in"] = ((pd.to_datetime(df.ts_fill) - pd.Timestamp("1970-01-01")).dt.total_seconds() // 60).astype("int64")
    df["t_out"] = ((pd.to_datetime(df.exit_ts) - pd.Timestamp("1970-01-01")).dt.total_seconds() // 60).astype("int64")
    df = df[df.t_out > df.t_in].copy()
    L = df["dir"] == "LONG"; S = df["dir"] == "SHORT"
    g = df[df.year >= 2024].copy()
    Lg = g["dir"] == "LONG"; Sg = g["dir"] == "SHORT"
    print("\n=== ПОРТФЕЛЬ 2024-26 ($100, 7 слотов, 1%) ===", flush=True)
    for n, m in {
        "raw": pd.Series(True, index=g.index),
        "ДЕПЛОЙ vwap": (Sg & (g.vd_conf <= 0)) | (Lg & (g.vd_conf >= 0)),
        "ТРЕНД ДН (L>EMA50д)": (Lg & (g.trend > 0)) | (Sg & (g.trend < 0)),
        "ТРЕНД 4H (L>E20/S<E20)": (Lg & (g.t4_e20 > 0)) | (Sg & (g.t4_e20 < 0)),
        "L>E20_4H & vd>=0 / S все": (Lg & (g.t4_e20 > 0) & (g.vd_conf >= 0)) | Sg,
        "L>E20_4H & slope>0 / S все": (Lg & (g.t4_e20 > 0) & (g.t4_slope > 0)) | Sg,
    }.items():
        fin, mdd, nn = portfolio(g[m.fillna(False)])
        print(f"  {n:28} | взято {nn:5d} | ${fin:>10,.0f} | MaxDD {mdd:>6.1f}%", flush=True)
    print("\nDONE", flush=True)


if __name__ == "__main__":
    main()

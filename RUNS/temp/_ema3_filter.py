"""EMA3-фильтр наклона HTF (как в forex/1m→1H линии) на нашем лимитном потоке.

Идея из архива: EMA span=3 на HTF (tf7→4H, tf8→8H; плюс вариант 1H), наклон lag=1;
для лонга наклон > +thr, для шорта < −thr. Каузально: только ЗАКРЫТЫЕ HTF-бакеты к from_ts.

Также вариант «позиция» (close vs EMA3) и пороги в широком диапазоне (4H/8H шумнее).
"""
import heapq
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, r"D:/PYTHON")
sys.path.insert(0, r"D:/PYTHON/CISDBOT")
from backtest.data import load_ltf

BASE = r"D:/PYTHON/cisdbotbybit/RUNS/temp"
RULES_TF = {"4h": "tf7", "8h": "tf8", "1h": "h1"}
THRS = (0.0, 0.0001, 0.0002, 0.0004, 0.001, 0.002, 0.005)


def wr(g):
    d = g[g.outcome.isin(["tp", "sl"])]
    return 100.0 * (d.outcome == "tp").mean() if len(d) else float("nan")


df = pd.read_pickle(f"{BASE}/stream_reanchor_full.pkl").copy()
df["from_ts"] = pd.to_datetime(df["from_ts"])
for tag in RULES_TF:
    df[f"slope_{tag}"] = np.nan
    df[f"pos_{tag}"] = np.nan
for sym in sorted(df.sym.unique()):
    d30, _ = load_ltf(tf="30m", since="2020-01-01", until="2026-12-31", symbol=sym)
    d30.index = pd.DatetimeIndex(d30.index)
    idx = df.index[df.sym == sym]
    fts = df.loc[idx, "from_ts"].to_numpy()
    for rule, tag in RULES_TF.items():
        h = pd.DataFrame({"close": d30["close"].resample(rule, label="left", closed="left").last()}).dropna()
        e3 = h["close"].ewm(span=3, adjust=False, min_periods=3).mean()
        sl = (e3 / e3.shift(1) - 1.0)
        labels_end = (h.index + pd.Timedelta(rule)).to_numpy()
        i = np.searchsorted(labels_end, fts, "right") - 1
        good = (i >= 3) & (i < len(h))
        pos = np.clip(np.where(good, i, 0), 0, len(h) - 1)
        cl = h["close"].to_numpy(float); ea = e3.to_numpy(float); sa = sl.to_numpy(float)
        df.loc[idx, f"slope_{tag}"] = np.where(good, sa[pos], np.nan)
        df.loc[idx, f"pos_{tag}"] = np.where(good & (ea[pos] > 0), cl[pos] / ea[pos] - 1.0, np.nan)
    print(f"  [{sym}] ok", flush=True)
df.to_pickle(f"{BASE}/stream_ema3.pkl")

L = df["dir"] == "LONG"; S = df["dir"] == "SHORT"; V = df.vd_conf
D = (S & (V <= 0)) | (L & (V >= 0))
print("\n=== EMA3 slope: ΣR (весь / 2024-26) — правило «лонг наклон>+thr, шорт <-thr», шорты/лонги без фильтра ===", flush=True)
for rule, tag in RULES_TF.items():
    s = df[f"slope_{tag}"]
    for thr in THRS:
        m = (L & (s > thr)) | (S & (s < -thr))
        mlong = (L & (s > thr)) | S
        g = df[m.fillna(False)]; g4 = g[g.year >= 2024]
        gl = df[mlong.fillna(False)]; gl4 = gl[gl.year >= 2024]
        print(f"  {rule:3} thr={100*thr:5.2f}% | оба: n={len(g):6d} ΣR={g.r_net.sum():+8.1f} (2024-26 {g4.r_net.sum():+7.1f}) | "
              f"только лонги: ΣR={gl.r_net.sum():+8.1f} (2024-26 {gl4.r_net.sum():+7.1f})", flush=True)

print("\n=== EMA3 position (close vs EMA3) ===", flush=True)
for rule, tag in RULES_TF.items():
    p = df[f"pos_{tag}"]
    m = (L & (p > 0)) | (S & (p < 0))
    mlong = (L & (p > 0)) | S
    g = df[m.fillna(False)]; g4 = g[g.year >= 2024]
    gl = df[mlong.fillna(False)]; gl4 = gl[gl.year >= 2024]
    print(f"  {rule:3} | оба: n={len(g):6d} ΣR={g.r_net.sum():+8.1f} (2024-26 {g4.r_net.sum():+7.1f}) | "
          f"только лонги: ΣR={gl.r_net.sum():+8.1f} (2024-26 {gl4.r_net.sum():+7.1f})", flush=True)


def portfolio(d, risk=0.01, start=100.0, maxpos=7):
    d = d.sort_values("t_in")
    it = list(zip(d.t_in.astype("int64"), d.t_out.astype("int64"), d.sym, d.r_net.astype(float)))
    pe, hp, tk = {}, [], []
    for tin, tout, (sym, r) in [(a, b, (c, dd)) for a, b, c, dd in it]:
        while hp and hp[0] <= tin:
            heapq.heappop(hp)
        p = pe.get(sym)
        if p is not None and tin < p:
            continue
        if len(hp) >= maxpos:
            continue
        tk.append((tin, tout, r)); heapq.heappush(hp, tout); pe[sym] = tout
    ev = []
    for i, (tin, tout, r) in enumerate(tk):
        ev.append((tin, 1, i)); ev.append((tout, 0, i))
    ev.sort(key=lambda e: (e[0], e[1], e[2]))
    bal = start; rm = {}; cur = [(ev[0][0] if ev else 0, bal)]
    for t, kk, i in ev:
        tin, tout, r = tk[i]
        if kk == 0:
            if i in rm:
                bal += rm.pop(i) * r
        else:
            if tout <= tin:
                bal += bal * risk * r
            else:
                rm[i] = bal * risk
        cur.append((t, bal))
    s = pd.Series([c[1] for c in cur])
    return bal, float(((s - s.cummax()) / s.cummax()).min() * 100), len(tk)


df["t_in"] = ((pd.to_datetime(df.ts_fill) - pd.Timestamp("1970-01-01")).dt.total_seconds() // 60).astype("int64")
df["t_out"] = ((pd.to_datetime(df.exit_ts) - pd.Timestamp("1970-01-01")).dt.total_seconds() // 60).astype("int64")
df = df[df.t_out > df.t_in].copy()
L = df["dir"] == "LONG"; S = df["dir"] == "SHORT"; V = df.vd_conf
D = (S & (V <= 0)) | (L & (V >= 0))
g = df[df.year >= 2024].copy()
Lg = g["dir"] == "LONG"; Sg = g["dir"] == "SHORT"; Dg = (Sg & (g.vd_conf <= 0)) | (Lg & (g.vd_conf >= 0))
print("\n=== ПОРТФЕЛЬ 2024-26 ($100, 7 слотов) ===", flush=True)
rows = [("raw", pd.Series(True, index=g.index)), ("ДЕПЛОЙ vwap", Dg)]
for rule, tag in RULES_TF.items():
    s = g[f"slope_{tag}"]
    rows.append((f"EMA3 {rule} thr0 оба", (Lg & (s > 0)) | (Sg & (s < 0))))
    rows.append((f"EMA3 {rule} thr0.02% оба", (Lg & (s > 0.0002)) | (Sg & (s < -0.0002))))
    rows.append((f"EMA3 {rule} thr0.02% лонги", (Lg & (s > 0.0002)) | Sg))
    rows.append((f"ДЕПЛОЙ+EMA3 {rule} 0.02% лонги", (Dg & ((g["dir"] != "LONG") | (s > 0.0002)))))
for lab, m in rows:
    fin, mdd, n = portfolio(g[m.fillna(False)].copy())
    print(f"  {lab:32} | взято {n:5d} | ${fin:>10,.0f} | MaxDD {mdd:>6.1f}%", flush=True)
print("\nDONE", flush=True)

"""ПРОВЕРКА ЯКОРЯ EMA3-фильтра: не подглядывает ли он в будущее.

1) Строгая проверка по КАЖДОЙ сделке: используемый 1H-бакет закрыт СТРОГО ДО (<=) from_ts;
   печатаю примеры с реальными окнами бакетов и барами 30m внутри.
2) Вариант lag1: наклон по бакету, закрытому за час ДО from_ts (инфа точно доступна).
3) Контроль future: наклон по бакету, закрывающемуся через час ПОСЛЕ from_ts (недоступен live).
   Если future резко лучше lag0 — фильтр «говорит да задним числом».
"""
import sys
import heapq

import numpy as np
import pandas as pd

sys.path.insert(0, r"D:/PYTHON")
sys.path.insert(0, r"D:/PYTHON/CISDBOT")
from backtest.data import load_ltf

BASE = r"D:/PYTHON/cisdbotbybit/RUNS/temp"
df = pd.read_pickle(f"{BASE}/stream_ema3.pkl")
df["from_ts"] = pd.to_datetime(df["from_ts"])

rows_ok = []
examples = []
viol = 0
for sym in sorted(df.sym.unique()):
    d, _ = load_ltf(tf="30m", since="2020-01-01", until="2026-12-31", symbol=sym)
    d.index = pd.DatetimeIndex(d.index)
    h = d["close"].resample("1h", label="left", closed="left").last().dropna()
    ends = (h.index + pd.Timedelta("1h")).to_numpy()
    idx = df.index[df.sym == sym]
    fts = df.loc[idx, "from_ts"].to_numpy()
    i = np.searchsorted(ends, fts, "right") - 1
    good = (i >= 3) & (i < len(h))
    pos = np.clip(np.where(good, i, 0), 0, len(h) - 1)
    # ПРОВЕРКА: конец бакета <= from_ts
    ok = ends[pos] <= fts
    viol += int((good & ~ok).sum())
    e3 = h.ewm(span=3, adjust=False, min_periods=3).mean()
    sl = (e3 / e3.shift(1) - 1.0).to_numpy()
    sl_lag = np.roll(sl, 1)  # наклон по бакету i-1
    sl_fut = np.roll(sl, -1)  # наклон по бакету i+1 (БУДУЩЕЕ, недоступно)
    sl_lag_vals = np.where(pos > 3, sl_lag[pos], np.nan)
    sl_fut_vals = np.where(pos < len(h) - 1, sl_fut[pos], np.nan)
    df.loc[idx, "s_now"] = np.where(good, sl[pos], np.nan)
    df.loc[idx, "s_lag1"] = np.where(good, sl_lag_vals, np.nan)
    df.loc[idx, "s_future"] = np.where(good, sl_fut_vals, np.nan)
    df.loc[idx, "bucket_end"] = np.where(good, ends[pos], np.datetime64("NaT"))
    if len(examples) < 6 and sym in ("SOL", "BTC"):
        for j_i in range(len(idx)):
            if good[j_i] and len(examples) < 6 and j_i < 3:
                j = idx[j_i]
                examples.append((sym, df.at[j, "from_ts"], pd.Timestamp(ends[pos[j_i]]), h.index[pos[j_i]]))
    print(f"  [{sym}] проверено, нарушений пока нет ({viol})", flush=True)

print(f"\n=== СТРОГАЯ ПРОВЕРКА: бакетов, у которых конец > from_ts: {viol} (должно быть 0) ===")
print("  примеры (символ, якорь from_ts, конец использованного 1H-бакета, начало бакета):")
for sym, f0, be, bs in examples[:6]:
    print(f"    {sym}: from_ts={pd.Timestamp(f0)} | бакет [{pd.Timestamp(bs)} → {pd.Timestamp(be)}) | зазор до якоря: {pd.Timestamp(f0)-pd.Timestamp(be)}")
print(f"  всего строк с непустым наклоном: {int(df.s_now.notna().sum())}")
print(f"  максимальный зазор (from_ts − bucket_end), мин: {(df.from_ts - df.bucket_end).min()}")

# --- симуляция портфеля на каждом варианте ---
tp = pd.read_pickle(f"{BASE}/stream_tp_grid.pkl")
kk = lambda d: d["hash"].astype(str) + "|" + d.prof.astype(str)
df["k"] = kk(df); tp["k"] = kk(tp)
mp = dict(zip(tp.k, tp["r_1_0"]))
df["r"] = [mp.get(x) for x in df.k]
df = df[df.r.notna()].copy()
df["t_in"] = ((pd.to_datetime(df.ts_fill) - pd.Timestamp("1970-01-01")).dt.total_seconds() // 60).astype("int64")
df["t_out"] = ((pd.to_datetime(df.exit_ts) - pd.Timestamp("1970-01-01")).dt.total_seconds() // 60).astype("int64")
df = df[df.t_out > df.t_in].copy()
L = df["dir"] == "LONG"; S = df["dir"] == "SHORT"; MS = df.sp >= 0.005


def pf(d, risk=0.01, start=100.0, maxpos=7):
    d = d.sort_values("t_in")
    it = list(zip(d.t_in.astype("int64"), d.t_out.astype("int64"), d.sym, d.r.astype(float)))
    pe, hp, tk = {}, [], []
    for tin, tout, sym, r in it:
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


def w(g):
    x = g[g.outcome.isin(["tp", "sl"])]
    return 100.0 * (x.outcome == "tp").mean() if len(x) else float("nan")


print("\n=== портфель 2024-26: now (боевой) vs lag1 (час назад) vs future (подглядывание, контроль) ===")
for tag, col in (("now (бакет закрыт <= from_ts)", "s_now"), ("lag1 (ещё час назад)", "s_lag1"),
                 ("future (НЕДОСТУПНО live)", "s_future")):
    s = df[col]
    m = ((L & (s > 0.0002)) | (S & (s < -0.0002))) & MS
    g = df[m.fillna(False)]
    g4 = g[g.year >= 2024]
    f4, d4, n4 = pf(g4.copy())
    print(f"  {tag:32} | 2024-26: взято {n4:5d} WR={w(g4):.1f}% avg={g4.r.mean():+.4f} ${f4:>8,.0f} MaxDD {d4:>6.1f}%")
print("\n=== для сравнения, что даёт АНТИ-версия (наклон ПРОТИВ сделки) ===")
s = df["s_now"]
m = ((L & (s < -0.0002)) | (S & (s > 0.0002)))
g = df[m.fillna(False)]; g4 = g[g.year >= 2024]
f4, d4, n4 = pf(g4.copy())
print(f"  anti (now)                       | 2024-26: взято {n4:5d} WR={w(g4):.1f}% avg={g4.r.mean():+.4f} ${f4:>8,.0f} MaxDD {d4:>6.1f}%")
print("\nDONE")

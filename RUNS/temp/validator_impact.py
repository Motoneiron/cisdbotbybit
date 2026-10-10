"""Влияние live-валидатора 'HTF без свипа' на поток: отмены + пересчёты.

Правило (как live): pending/сигнал отменяется, если у его HTF-окна нет Pine-свипа в его
направлении И сделка не была заполнена до закрытия окна.
"""
import heapq
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, r"D:/PYTHON")
sys.path.insert(0, r"D:/PYTHON/CISDBOT")
from backtest.data import load_ltf

df = pd.read_pickle(r"D:/PYTHON/cisdbotbybit/RUNS/temp/gate_trades_timed2.pkl")
print("сделок:", len(df), "| htf_time пусто:", int((df.htf_time == "").sum()))

flags = {}
for sym in sorted(df.sym.unique()):
    d1h, _ = load_ltf(tf="1h", since="2020-01-01", until="2026-12-31", symbol=sym)
    d1h.index = pd.DatetimeIndex(d1h.index)
    d4 = d1h.resample("4h", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"})
    d4 = d4.dropna(subset=["open"])
    for i in range(1, len(d4)):
        c2 = d4.iloc[i]; c3 = d4.iloc[i - 1]
        hh = bool(c2["high"] > c3["high"] and c2["close"] < c3["high"])
        ll = bool(c2["low"] < c3["low"] and c2["close"] > c3["low"])
        flags[(sym, str(d4.index[i]))] = (hh, ll)
    print(sym, "4H bars:", len(d4))

res = []
miss = 0
for row in df.itertuples():
    key = (row.sym, row.htf_time[:19])
    fl = flags.get(key)
    if fl is None:
        miss += 1
        res.append(False)
        continue
    hh, ll = fl
    ok = (ll and row.dir == "LONG") or (hh and row.dir == "SHORT")
    close_m = int(pd.Timestamp(row.htf_time[:19]).value // 60_000_000_000) + 240
    filled_before = bool(row.taken) and row.t_in is not None and int(row.t_in) < close_m
    res.append((not ok) and (not filled_before))
df["cancel_sw"] = res
print("окно не найдено:", miss)

tk = df[df.taken].copy()
canc = tk[tk.cancel_sw]
print(f"\n=== отменено правильным валидатором: {len(canc)} из {len(tk)} сд | ΣR отменённых: {canc.r.sum():+.1f} ===")
print("по направлениям:", {k: int(v) for k, v in canc.dir.value_counts().items()})

CUR = ((tk.dir == "LONG") & (tk.vd <= -3)) | ((tk.dir == "SHORT") & (tk.vd <= 0))
NEW = ((tk.dir == "LONG") & (tk.vd > 0)) | ((tk.dir == "SHORT") & (tk.vd <= 0))

for name, mask in (("cur (как было: L≤-3+S≤0)", CUR), ("new (L>0+S≤0)", NEW)):
    d0 = tk[mask]; d1 = tk[mask & ~tk.cancel_sw]
    tp0 = (d0.out == "tp").sum(); sl0 = (d0.out == "sl").sum()
    tp1 = (d1.out == "tp").sum(); sl1 = (d1.out == "sl").sum()
    print(f"\n{name}:")
    print(f"  было:  n={len(d0)} WR={100*tp0/max(1,tp0+sl0):.1f}% SumR={d0.r.sum():+.1f}")
    print(f"  стало: n={len(d1)} WR={100*tp1/max(1,tp1+sl1):.1f}% SumR={d1.r.sum():+.1f}  (Δ {d1.r.sum()-d0.r.sum():+.1f})")

print("\nпо годам (new-гейт, ΣR было → стало):")
for year in sorted(tk.year.unique()):
    d = tk[NEW & (tk.year == year)]
    c = d[d.cancel_sw]
    print(f"  {year}: {len(d)}/{d.r.sum():+.0f} → {len(d)-len(c)}/{d.r.sum()-c.r.sum():+.0f}")

# портфель (1 поз/пара + лимит 7, риск 1%, $100): до/после
def portfolio(d, max_pos=7):
    d = d.sort_values("t_in").reset_index(drop=True)
    taken, pair_end, heap = [], {}, []
    for row in d.itertuples():
        tin, tout, sym = int(row.t_in), int(row.t_out), row.sym
        while heap and heap[0] <= tin:
            heapq.heappop(heap)
        if sym in pair_end and tin < pair_end[sym]:
            continue
        if max_pos and len(heap) >= max_pos:
            continue
        taken.append(row)
        heapq.heappush(heap, tout)
        pair_end[sym] = tout
    ev = []
    for idx, row in enumerate(taken):
        tin, tout = int(row.t_in), int(row.t_out)
        ev.append((tin, 1, idx))
        if tout > tin:
            ev.append((tout, 0, idx))
    ev.sort(key=lambda e: (e[0], e[1], e[2]))
    balance = 100.0
    risks = {}
    for t, kind, idx in ev:
        row = taken[idx]
        if kind == 0:
            if idx in risks:
                balance += risks.pop(idx) * float(row.r)
        else:
            rr = balance * 0.01
            if int(row.t_out) <= int(row.t_in):
                balance += rr * float(row.r)
            else:
                risks[idx] = rr
    return balance

for name, mask in (("cur", CUR), ("new", NEW)):
    f0 = portfolio(tk[mask])
    f1 = portfolio(tk[mask & ~tk.cancel_sw])
    print(f"\nпортфель {name}: без валидатора ×{f0/100:,.0f} → с валидатором ×{f1/100:,.0f}")

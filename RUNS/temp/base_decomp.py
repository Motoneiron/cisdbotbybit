"""Разложение BASE_rerun: сколько из Bybit-результата — дельта комиссий.

delta = ставки MEXC(0.60/0.80 tp_maker) - ставки Bybit(0.36/1.00 tp_maker), в R на сделку.
"""
import glob
import pickle

import pandas as pd

rows = []
for f in glob.glob(r"D:/PYTHON/cisdbotbybit/RUNS/temp/tf7_abl/BASE_rerun_*.pkl"):
    rows.extend(pickle.load(open(f, "rb")))
d = pd.DataFrame(rows)
print("сделок:", len(d))

def fr(k, o, s, m, t):
    if not s or s <= 0:
        return 0.0
    e = m if str(k).upper() == "LIMIT" else t
    x = m if o == "tp" else t
    return (e + x) / s

d["delta"] = [
    fr(k, o, s, 0.0006, 0.0008) - fr(k, o, s, 0.00036, 0.0010)
    for k, o, s in zip(d.entry_kind, d.outcome, d.sp)
]
d["r_byb"] = d.r_net_mexc + d["delta"]

print("\nпо годам (avg R на сделку):")
for y in sorted(d.year.unique()):
    q = d[d.year == y]
    share = 100 * q["delta"].mean() / q.r_byb.mean() if q.r_byb.mean() else 0
    print(f"  {y}: n={len(q):>5} | MEXC {q.r_net_mexc.mean():+.4f} | Bybit {q.r_byb.mean():+.4f} | "
          f"дельта комиссий {q['delta'].mean():+.4f} | доля дельты в Bybit {share:.0f}%")

print("\nвсего:")
print(f"  MEXC avg {d.r_net_mexc.mean():+.4f} (Sum {d.r_net_mexc.sum():+.0f})")
print(f"  Bybit avg {d.r_byb.mean():+.4f} (Sum {d.r_byb.sum():+.0f})")
print(f"  дельта avg {d['delta'].mean():+.4f} (Sum {d['delta'].sum():+.0f})")
print(f"  доля дельты в Bybit-сумме: {100*d['delta'].sum()/d.r_byb.sum():.0f}%")

print("\nпо исходу (LIMIT-only, avg R):")
g = d.groupby("outcome")[["r_net_mexc", "r_byb", "delta"]].agg(["mean", "count"]).round(4)
print(g.to_string())

print("\n24-26 отдельно:")
q = d[d.year.astype(int) >= 2024]
print(f"  MEXC {q.r_net_mexc.mean():+.4f} | Bybit {q.r_byb.mean():+.4f} | дельта {q['delta'].mean():+.4f}")
print(f"  доля дельты в Bybit-сумме 24-26: {100*q['delta'].sum()/q.r_byb.sum():.0f}%")
print("\nтоп-10 сделок по |r_byb|:")
print(d.reindex(d.r_byb.abs().sort_values(ascending=False).index).head(10)[
    ["sym", "year", "direction", "outcome", "sp", "r_net_mexc", "r_byb"]].to_string())
print("\nдисперсия r_byb:", round(d.r_byb.std(), 2), "| r_net_mexc:", round(d.r_net_mexc.std(), 2))

"""LONG: бакеты vd и по парам — есть ли выжившие зоны."""
import pickle

import pandas as pd

d = pickle.load(open(r"D:/PYTHON/CISDBOT/RUNS/temp/vwap_all_filters_off.pkl", "rb"))
lon = d[d.direction == "LONG"].copy()

bins = [-100, -8, -6, -4, -3, -2, 0, 2, 4, 100]
labels = ["<-8", "-8..-6", "-6..-4", "-4..-3", "-3..-2", "-2..0", "0..2", "2..4", ">4"]
lon["bucket"] = pd.cut(lon.vd, bins=bins, labels=labels)
g = lon.groupby("bucket", observed=True).agg(n=("r", "size"), sumr=("r", "sum"), wr_pct=("o1", lambda s: 100 * (s == "tp").mean()))
print("=== LONG по бакетам vd (сырой поток, TP1R-исход) ===")
print(g.round(1).to_string())

print("\n=== LONG при vd<=-3 по парам ===")
l3 = lon[lon.vd <= -3]
g2 = l3.groupby("symbol").agg(n=("r", "size"), sumr=("r", "sum"))
print(g2.round(1).to_string())

print("\n=== LONG при vd<=-3 по ТФ ===")
g3 = l3.groupby("profile").agg(n=("r", "size"), sumr=("r", "sum"))
print(g3.round(1).to_string())

# для полноты: все лонги сырого потока
print(f"\nВсе LONG сырого потока (любой vd): n={len(lon)} SumR={lon.r.sum():+.1f}")
print(f"LONG vd>-3 (гейтом отсекались): n={(lon.vd > -3).sum()} SumR={lon[lon.vd > -3].r.sum():+.1f}")
g4 = lon[lon.vd > -3].groupby("bucket", observed=True).agg(n=("r", "size"), sumr=("r", "sum"))
print(g4.round(1).to_string())

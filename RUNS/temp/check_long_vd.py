"""LONG при vd<=-3: сумма по годам. Проверка утверждения про -317R."""
import pickle

import pandas as pd

d = pickle.load(open(r"D:/PYTHON/CISDBOT/RUNS/temp/vwap10_all_df.pkl", "rb"))

print("### vwap10_all_df (vwap-поток 10128): ######")
print("Проверка гейта: LONG min vd =", d[d.direction == "LONG"].vd.min(),
      "| SHORT max vd =", d[d.direction == "SHORT"].vd.max())

for col, label in (("r_1r", "TP1R"), ("r_native", "родной TP")):
    print(f"\n--- LONG @ vd<=-3, исходы {label} ---")
    g = d[d.direction == "LONG"].groupby("year").agg(n=("r", "size"), sumr=(col, "sum"))
    g["avg"] = g.sumr / g.n
    print(g.round(2).to_string())
    tot = d[d.direction == "LONG"][col].sum()
    print(f"ИТОГО LONG: n={len(d[d.direction == 'LONG'])} SumR={tot:+.1f}")

print("\n--- SHORT (vd<=0) для сравнения, TP1R ---")
g = d[d.direction == "SHORT"].groupby("year").agg(n=("r_1r", "size"), sumr=("r_1r", "sum"))
print(g.round(1).to_string())
print(f"ИТОГО SHORT: n={len(d[d.direction == 'SHORT'])} SumR={d[d.direction == 'SHORT'].r_1r.sum():+.1f}")

# альтернатива: без vwap, сами применяем гейт
d2 = pickle.load(open(r"D:/PYTHON/CISDBOT/RUNS/temp/vwap_all_filters_off.pkl", "rb"))
print("\n### vwap_all_filters_off (33763, гейт применяем сами): ######")
lon = d2[(d2.direction == "LONG") & (d2.vd <= -3)]
sht = d2[(d2.direction == "SHORT") & (d2.vd <= 0)]
print(f"LONG vd<=-3: n={len(lon)} SumR={lon.r.sum():+.1f}")
g = lon.groupby(pd.to_datetime(lon.entry).dt.year).agg(n=("r", "size"), sumr=("r", "sum"))
print(g.round(1).to_string())
print(f"\nSHORT vd<=0: n={len(sht)} SumR={sht.r.sum():+.1f}")

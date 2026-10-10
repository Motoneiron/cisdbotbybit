"""Как выглядела калибровка: SOL tf7 2024 (где заморозили порог)."""
import pickle

import pandas as pd

d = pickle.load(open(r"D:/PYTHON/CISDBOT/RUNS/temp/vwap_all_filters_off.pkl", "rb"))
lon = d[d.direction == "LONG"].copy()
lon["year"] = pd.to_datetime(lon.entry).dt.year
lon["zone"] = pd.cut(lon.vd, [-100, -3, 0, 4, 100], labels=["vd<=-3", "-3..0", "0..4", ">4"])

cal = lon[(lon.symbol == "SOL") & (lon.profile == "tf7") & (lon.year == 2024)]
print("SOL tf7 2024 (где калибровали порог):")
print(cal.groupby("zone", observed=True).agg(n=("r", "size"), sumr=("r", "sum")).round(1).to_string())

cal2 = lon[(lon.symbol == "SOL") & (lon.profile == "tf7")]
print("\nSOL tf7 все годы:")
print(cal2.groupby("zone", observed=True).agg(n=("r", "size"), sumr=("r", "sum")).round(1).to_string())

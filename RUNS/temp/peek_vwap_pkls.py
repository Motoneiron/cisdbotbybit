"""Проверка: LONG при vd<=-3 — минус ли по эпохам? Что в pkl-файлах."""
import pickle

import pandas as pd

for name in ("vwap10_all_df.pkl", "vwap_all_filters_off.pkl", "vwap_with_sp.pkl"):
    for base in (r"D:/PYTHON/CISDBOT/RUNS/temp", r"D:/PYTHON/cisdbotbybit/RUNS/temp"):
        try:
            d = pickle.load(open(f"{base}/{name}", "rb"))
        except Exception:
            continue
        print(f"=== {name} @ {base} ===")
        if isinstance(d, dict):
            print("  dict keys:", list(d.keys())[:10])
            df = None
            for k, v in d.items():
                if isinstance(v, pd.DataFrame):
                    df = v
                    print(f"  DataFrame[{k}]: {v.shape} cols={list(v.columns)}")
                    break
                if isinstance(v, list) and v and isinstance(v[0], dict):
                    df = pd.DataFrame(v)
                    print(f"  list[{k}]: {len(v)} rows, cols={list(df.columns)}")
                    break
        elif isinstance(d, pd.DataFrame):
            df = d
            print("  DataFrame:", d.shape, list(d.columns))
        else:
            print("  type:", type(d))
            continue
        if df is not None and not df.empty:
            print("  head:")
            print(df.head(3).to_string())
            if "year" in df.columns:
                print("  years:", sorted(df.year.unique()))
        print()
        break

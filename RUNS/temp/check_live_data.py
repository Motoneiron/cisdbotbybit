"""Инвентарь live-данных: покрытие 5m/1m SOL (MEXC) за период живых сделок."""
import os
import pandas as pd

base = r"D:/PYTHON/CISDBOT/.tmp_live_compare"
files = [
    "SOLUSDT_5m_mexc_2026-07.csv",
    "SOLUSDT_1m_mexc_live_window.csv",
    "SOLUSDT_1m_mexc_2w.csv",
]
for f in files:
    p = os.path.join(base, f)
    if not os.path.exists(p):
        print(f, "НЕТ")
        continue
    df = pd.read_csv(p, usecols=[0])
    c0 = df.columns[0]
    print(f"{f}: rows={len(df)} | {df[c0].iloc[0]} -> {df[c0].iloc[-1]} | cols={c0}")

# ищем любые другие свежие 5m/1m SOL файлы по диску (cisdbotbybit + CISDBOT)
import glob
pats = [
    r"D:/PYTHON/cisdbotbybit/RUNS/temp/**/*SOL*5m*.csv",
    r"D:/PYTHON/cisdbotbybit/RUNS/temp/**/*SOL*1m*.csv",
    r"D:/PYTHON/CISDBOT/**/*SOL*2026-0*.csv",
    r"D:/PYTHON/CISDBOT/data/**/*SOL*.csv",
]
seen = set()
for pat in pats:
    for p in glob.glob(pat, recursive=True):
        if p in seen:
            continue
        seen.add(p)
        try:
            df = pd.read_csv(p, usecols=[0])
            print(f"{p}: rows={len(df)} | {df.iloc[0,0]} -> {df.iloc[-1,0]}")
        except Exception as e:
            print(f"{p}: ERR {e}")

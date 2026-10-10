"""check_notseen_mech.py — почему канонный MEXC-детект не видит notseen-сигналы?

Берём notseen-сделки (scan-бары живого) и вызываем MEXC-детект:
  - на баре scan (когда живой взял сделку)
  - на следующем :20-баре (канонный скан-грид)
  - ещё через час (:20)
Печатаем все выдачи (cbt/hash/fib).
"""
import logging
import sys

sys.path.insert(0, r"D:/PYTHON/CISDBOT")
logging.disable(logging.CRITICAL)
import numpy as np
import pandas as pd
import cisdbot as bot

PATHS = {
    "SOL": r"D:/databtcusdt/SOLUSDT-1m/SOLUSDT_1m_full_hdr.csv",
    "DOGE": r"D:/databtcusdt/DOGEUSDT-1m/DOGEUSDT_1m_full_hdr.csv",
    "KAS": r"D:/databtcusdt/KASUSDT-1m/KASUSDT_1m_full_hdr.csv",
    "ADA": r"D:/databtcusdt/ADAUSDT-1m-merged.csv",
    "LINK": r"D:/databtcusdt/LINKUSDT-1m-merged.csv",
    "LTC": r"D:/databtcusdt/LTCUSDT-1m-merged.csv",
}


def load_1m(path, since, until):
    t0 = pd.Timestamp(since) - pd.Timedelta(days=4)
    t1 = pd.Timestamp(until) + pd.Timedelta(days=1)
    parts = []
    cols = ["open_time", "open", "high", "low", "close", "volume"]
    for chunk in pd.read_csv(path, usecols=cols, chunksize=500_000):
        ot = pd.to_datetime(chunk["open_time"], unit="ms")
        m = (ot >= t0) & (ot < t1)
        if not m.any():
            if len(ot) and ot.iloc[-1] < t0:
                continue
            if len(ot) and ot.iloc[0] >= t1:
                break
            continue
        sub = chunk.loc[m, ["open", "high", "low", "close", "volume"]].astype(float)
        sub.index = ot[m]
        parts.append(sub)
    df = pd.concat(parts)
    return df[~df.index.duplicated(keep="last")].sort_index()
HF = int(bot.CONFIG["tf7"]["htf_ratio"])
A = pd.read_csv("classify6_out.csv")
A["scan"] = pd.to_datetime(A["scan"])

for sym, path in PATHS.items():
    df1 = load_1m(path, "2024-01-01", "2025-01-01")
    if df1.empty:
        print(f"\n########## {sym}: нет данных")
        continue
    df5 = bot._resample_ohlcv(df1, "5m")
    cases = []
    o = A[(A.sym == sym) & (A.cls == "notseen")].head(8)
    p = A[(A.sym == sym) & (A.cls == "paired")].head(3)
    for _, row in o.iterrows():
        cases.append(("notseen", row))
    for _, row in p.iterrows():
        cases.append(("paired ", row))
    print(f"\n########## {sym} ##########")
    for tag, row in cases:
        scan = row["scan"]
        i = int(df5.index.searchsorted(scan))
        if i >= len(df5) or i < 300:
            continue
        after = df5.index[i:]
        n20 = after[after.minute == 20]
        checks = [scan]
        if len(n20):
            checks.append(n20[0])
            if len(n20) > 1:
                checks.append(n20[1])
        outs = []
        for c in checks:
            j = int(df5.index.searchsorted(c))
            if j < 300:
                continue
            sl = df5.iloc[j - 299 : j + 1]
            sigs = bot.detect_signals(sl, set(), htf_ratio=HF, tf_name="tf7", df_confirm=None, min_sweep_atr=0.0) or []
            t = ";".join(f"{s.get('direction')}@{str(s.get('confirm_bar_time'))[5:16]}" for s in sigs)
            outs.append(f"{str(c)[5:16]}->{t or '-'}")
        print(f"  [{tag}] scan={str(scan)[5:16]} {row['dir']} r={row['r']:+.2f} | " + " | ".join(outs), flush=True)

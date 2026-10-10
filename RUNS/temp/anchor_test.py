# anchor_test.py — сверка якоря slope: движок (C-1) vs бот (C-2) vs "идеал" (C).
# C = конфирм-бар (cbt). Движок: sv = slope[C-1]; бот: sv = slope[C-2].
import os
import pickle
import numpy as np
import pandas as pd

BASE = r"D:\PYTHON\cisdbotbybit\RUNS\temp\live_tf_stopt\stopt_tf1v2"
CSV = {
    "SOL": r"D:\databtcusdt\SOLUSDT-1m\SOLUSDT_1m_full_hdr.csv",
    "DOGE": r"D:\databtcusdt\DOGEUSDT-1m\DOGEUSDT_1m_full_hdr.csv",
    "KAS": r"D:\databtcusdt\KASUSDT-1m\KASUSDT_1m_full_hdr.csv",
    "ADA": r"D:\databtcusdt\ADAUSDT-1m-merged.csv",
    "LINK": r"D:\databtcusdt\LINKUSDT-1m-merged.csv",
    "LTC": r"D:\databtcusdt\LTCUSDT-1m-merged.csv",
    "XRP": r"D:\databtcusdt\XRPUSDT-1m-merged.csv",
    "BTC": r"D:\databtcusdt\BTCUSDT-1m\BTCUSDT_1m_2020_2026_conv.csv",
    "AVAX": r"D:\databtcusdt\AVAXUSDT-1m-merged.csv",
    "TON": r"D:\databtcusdt\TONUSDT-1m-merged.csv",
}
SYMS = list(CSV)
TH = 0.0002


def slope_series(path):
    dm = pd.read_csv(path, usecols=["open_time", "close"])
    dm["ts"] = pd.to_datetime(dm["open_time"], unit="ms")
    s = dm.set_index("ts")["close"]
    d15 = s.resample("15min", label="left", closed="left").last().dropna()
    ema = d15.ewm(span=21, adjust=False, min_periods=21).mean()
    return (ema / ema.shift(1) - 1.0)


def blocked(direction, sv):
    if sv is None or (isinstance(sv, float) and np.isnan(sv)):
        return None
    return (direction == "LONG" and sv <= TH) or (direction == "SHORT" and sv >= -TH)


tot = {"n": 0, "diff_bot": 0, "diff_ideal": 0, "nan": 0, "scan_off": 0}
rows_out = []
for sym in SYMS:
    files = [f for f in sorted(os.listdir(BASE)) if f.startswith(sym + "_")]
    if not files:
        continue
    sl = slope_series(CSV[sym])
    idx = sl.index
    n, d_bot, d_ideal, nan, scan_off = 0, 0, 0, 0, 0
    ex = []
    for f in files:
        for r in pickle.load(open(os.path.join(BASE, f), "rb")):
            cb = pd.Timestamp(r["cbt"])
            scan = pd.Timestamp(r["scan"])
            if (scan - cb).total_seconds() / 60 != 15:
                scan_off += 1
            if cb not in idx:
                nan += 1
                continue
            p = idx.get_loc(cb)
            if p < 3:
                nan += 1
                continue
            sv_d = sl.iloc[p - 1]   # движок: C-1
            sv_b = sl.iloc[p - 2]   # бот: C-2
            sv_i = sl.iloc[p]       # идеал: C
            n += 1
            bd, bb, bi = blocked(r["direction"], sv_d), blocked(r["direction"], sv_b), blocked(r["direction"], sv_i)
            if bd != bb:
                d_bot += 1
                if len(ex) < 6:
                    ex.append((f, r["direction"], str(cb), f"dvig={sv_d*100:+.4f}%", f"bot={sv_b*100:+.4f}%"))
            if bd != bi:
                d_ideal += 1
    print(f"{sym}: n={n} | движок-vs-бот различий: {d_bot} ({d_bot/n*100:.1f}%) | движок-vs-идеал: {d_ideal} ({d_ideal/n*100:.1f}%) | skip(nan)={nan} scan_off={scan_off}")
    for e in ex:
        print("   ", *e)
    tot["n"] += n; tot["diff_bot"] += d_bot; tot["diff_ideal"] += d_ideal; tot["nan"] += nan; tot["scan_off"] += scan_off

print(f"\nИТОГО: n={tot['n']} | движок-vs-бот: {tot['diff_bot']} ({tot['diff_bot']/tot['n']*100:.2f}%) | движок-vs-идеал(C): {tot['diff_ideal']} ({tot['diff_ideal']/tot['n']*100:.2f}%) | nan={tot['nan']} scan_off={tot['scan_off']}")

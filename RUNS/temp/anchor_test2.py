# anchor_test2.py — точная сверка: движок = slope[C-1], бот = slope[C-2]; доли блоков.
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


stats = {"n": 0, "d_tr": 0, "i_blk": 0, "b_blk": 0, "bot_extra_blk": 0, "bot_fewer_blk": 0}
true_blk_examples = []
for sym in CSV:
    files = [f for f in sorted(os.listdir(BASE)) if f.startswith(sym + "_")]
    if not files:
        continue
    sl = slope_series(CSV[sym])
    idx = sl.index
    n, d_tr, i_blk, b_blk, eb, fb, t_blk = 0, 0, 0, 0, 0, 0, 0
    for f in files:
        for r in pickle.load(open(os.path.join(BASE, f), "rb")):
            cb = pd.Timestamp(r["cbt"])
            if cb not in idx:
                continue
            p = idx.get_loc(cb)
            if p < 4:
                continue
            sv_dvig = sl.iloc[p - 1]   # движок: наклон на баре C-1  (подтверждено репродукцией)
            sv_bot = sl.iloc[p - 2]    # бот-кодер: наклон на баре C-2
            sv_ideal = sl.iloc[p]      # "последний закрытый": наклон на баре C
            n += 1
            bd = blocked(r["direction"], sv_dvig)
            bb = blocked(r["direction"], sv_bot)
            bi = blocked(r["direction"], sv_ideal)
            if bd:
                t_blk += 1
                true_blk_examples.append((sym, f, r["direction"], str(cb), f"{sv_dvig*100:+.4f}%"))
            i_blk += 1 if bi else 0
            b_blk += 1 if bb else 0
            if bb and not bd:
                eb += 1
            if bd and not bb:
                fb += 1
            if bd != bi:
                d_tr += 1
    print(f"{sym}: n={n} | блок C-1 (движок): {t_blk} | блок C-2 (бот): {b_blk} | блок C (идеал): {i_blk} | vs бот: +{eb}/-{fb}")
    stats["n"] += n; stats["d_tr"] += d_tr; stats["i_blk"] += i_blk; stats["b_blk"] += b_blk
    stats["bot_extra_blk"] += eb; stats["bot_fewer_blk"] += fb
print()
print("ИТОГО:", stats)
print("Примеры где C-1 давал бы БЛОК (не должно быть!):")
for e in true_blk_examples[:10]:
    print("  ", *e)

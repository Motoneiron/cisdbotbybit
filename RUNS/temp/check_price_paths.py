"""Проверка расхождений бэк↔живой по реальному пути цены (5m Bybit).
Кто прав: бэк или живой SHADOW-монитор.
"""
import pandas as pd

BASE = "D:/PYTHON/cisdbotbybit/RUNS/temp/data_recent"


def bars(sym, t0, t1):
    df = pd.read_csv(f"{BASE}/{sym}USDT_5m_recent.csv", parse_dates=["timestamp"])
    return df.loc[(df["timestamp"] >= t0) & (df["timestamp"] <= t1)]


def check(name, sym, t0, t1, tp, sl, entry, direction):
    d = bars(sym, t0, t1)
    if direction == "SHORT":
        hit_tp = d.loc[d["low"] <= tp]
        hit_sl = d.loc[d["high"] >= sl]
    else:
        hit_tp = d.loc[d["high"] >= tp]
        hit_sl = d.loc[d["low"] <= sl]
    ftp = hit_tp["timestamp"].iloc[0] if len(hit_tp) else None
    fsl = hit_sl["timestamp"].iloc[0] if len(hit_sl) else None
    print(f"{name}: {sym} {direction} entry {entry} tp {tp} sl {sl}")
    print(f"   первый тач TP: {ftp} | первый тач SL: {fsl}")
    if ftp is not None and fsl is not None:
        print(f"   -> РАНЬШЕ: {'TP' if ftp < fsl else 'SL'}")
    elif ftp is not None:
        print("   -> достигнут только TP")
    elif fsl is not None:
        print("   -> достигнут только SL")
    else:
        print("   -> не достигнут ни TP, ни SL")
    print(f"   экстремумы окна: high {d['high'].max():.6f} | low {d['low'].min():.6f} | баров {len(d)}")
    print()


check("SOL SHORT (бэк: SL -1.126 | живой: TP +0.827)", "SOL",
      "2026-09-16 13:00", "2026-09-17 02:00", 96.19, 98.29, 97.24, "SHORT")
check("DOGE LONG (бэк: time +0.433 | живой: TP +0.840)", "DOGE",
      "2026-09-16 18:05", "2026-09-17 00:30", 0.08024, 0.07824, 0.07924, "LONG")
check("ETH SHORT (бэк: time -0.712 | живой: SL -0.912)", "ETH",
      "2026-09-16 19:30", "2026-09-17 02:00", 2345.36, 2429.98, 2387.67, "SHORT")

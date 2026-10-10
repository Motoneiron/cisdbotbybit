# test_pairs.py — проверка чтения 4 новых пар движком.
import sys
sys.path.insert(0, r"D:\PYTHON\cisdbotbybit\RUNS\temp")
from stop_timing_run import load_1m, PATHS

for sym in ["ETH", "BNB", "XRP", "TON"]:
    # начало 2024 (быстро: читается только начало файла)
    a = load_1m(PATHS[sym], "2024-01-01", "2024-01-08")
    # конец (полный проход)
    b = load_1m(PATHS[sym], "2026-08-25", "2026-09-02")
    fmt = lambda d: (len(d), str(d.index.min())[:16] if len(d) else "-", str(d.index.max())[:16] if len(d) else "-")
    print(sym, "начало2024:", fmt(a), "| конец2026:", fmt(b))
    if len(b):
        print("   close nan:", int(b["close"].isna().sum()), "| zero-bars:", int(((b["high"] - b["low"]) == 0).sum()), "| last close:", float(b["close"].iloc[-1]))

"""Recon перед снапшотом честного потока: структура кэшей + данные + поля."""
import glob
import pickle
import sys
from collections import Counter

sys.path.insert(0, r"D:/PYTHON")
sys.path.insert(0, r"D:/PYTHON/CISDBOT")

# --- 1) какие кэши есть
for prof in ("tf7", "tf8"):
    n = Counter()
    for sym in ("BTC", "ETH", "DOGE", "KAS", "ADA", "BNB", "LINK", "LTC", "XRP", "SOL"):
        for p in glob.glob(rf"D:/PYTHON/CISDBOT/RUNS/*/bot_aligned/{sym}_{prof}_*.pkl"):
            n[sym] += 1
    print(f"{prof}: " + ", ".join(f"{k}:{v}" for k, v in sorted(n.items())))

# --- 2) структура одного кэша
paths = sorted(glob.glob(r"D:/PYTHON/CISDBOT/RUNS/*/bot_aligned/SOL_tf7_*.pkl"))
print("\nSOL tf7 files (last 3):")
for p in paths[-3:]:
    print("  ", p)
c = pickle.load(open(paths[-1], "rb"))
print("cache keys:", list(c.keys()))
sigs = c.get("signals") or []
trades = c.get("trades") or []
print("signals:", len(sigs), " trades:", len(trades))

print("\n--- sample signal fields:")
if sigs:
    for k, v in sigs[0].items():
        print(f"  {k!r}: {str(v)[:100]!r}")

print("\n--- sample trade fields:")
td = None
for t in trades:
    if t.get("entry_kind") == "LIMIT":
        td = t
        break
if td is None and trades:
    td = trades[0]
if td is not None:
    for k, v in td.items():
        print(f"  {k!r}: {str(v)[:100]!r}")

print("\nentry_kinds:", Counter(t.get("entry_kind") for t in trades))
print("outcomes:", Counter(t.get("outcome") for t in trades))

# --- 3) данные: что видит load_ltf
from backtest.data import load_ltf
df, _ = load_ltf(tf="5m", since="2024-01-01", until="2024-01-05", symbol="SOL")
print("\nload_ltf SOL 5m cols:", list(df.columns), " len:", len(df))
print(df.head(2).to_string())

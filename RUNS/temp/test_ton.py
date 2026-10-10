# test_ton.py — анализ TON: где живые данные; + ETH контроль середины.
import sys
sys.path.insert(0, r"D:\PYTHON\cisdbotbybit\RUNS\temp")
from stop_timing_run import load_1m, PATHS

e = load_1m(PATHS["ETH"], "2026-06-01", "2026-06-10")
print("ETH 2026-06:", len(e), "| zero-bars:", int(((e["high"] - e["low"]) == 0).sum()), "| vol==0:", int((e["volume"] == 0).sum()))

t = load_1m(PATHS["TON"], "2024-01-01", "2026-09-08")
print("TON всего:", len(t), str(t.index.min())[:16], "->", str(t.index.max())[:16])
t2 = t.copy()
t2["zero"] = (t2["high"] - t2["low"]) == 0
t2["vol0"] = t2["volume"] == 0
g = t2.groupby(t2.index.to_period("M")).agg(n=("close", "size"), zero=("zero", "sum"), vol0=("vol0", "sum"))
print(g.to_string())

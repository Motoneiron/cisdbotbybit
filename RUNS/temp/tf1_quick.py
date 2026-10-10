# Быстрый претест: ОДНА пара + ОДИН год (default SOL/2025) на выбранном режиме.
# usage: python tf1_quick.py <mode> [SYM=SOL] [YEAR=2025] [MONTHS=0]
# MONTHS>0 — только первые N месяцев года (для отладки).
import sys
sys.path.insert(0, r"D:\PYTHON\cisdbotbybit")
sys.path.insert(0, r"D:\PYTHON\cisdbotbybit\RUNS\temp")
import pandas as pd
import live_tf_grid as g

mode = sys.argv[1]
sym = sys.argv[2] if len(sys.argv) > 2 else "SOL"
year = int(sys.argv[3]) if len(sys.argv) > 3 else 2025
months = int(sys.argv[4]) if len(sys.argv) > 4 else 0

if mode not in g.MODES:
    print(f"неизвестный режим {mode}", flush=True)
    sys.exit(2)

g.MODE = mode
g.OUT_DIR = mode
g.SMOKE = False
if months > 0:
    until = (pd.Timestamp(f"{year}-01-01") + pd.DateOffset(months=months)).strftime("%Y-%m-%d")
    g.YEARS = [(year, f"{year}-01-01", until)]
else:
    g.YEARS = [(year, f"{year}-01-01", f"{year + 1}-01-01")]

print(f"=== QUICK mode={mode} sym={sym} {g.YEARS} ===", flush=True)
print(g.run_symbol(sym), flush=True)

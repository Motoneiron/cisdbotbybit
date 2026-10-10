# quick_tp.py — быстрый прогон SOL/2025 для режима TP-сетки (аргумент: режим).
import sys
sys.path.insert(0, r"D:\PYTHON\cisdbotbybit\RUNS\temp")
import stop_timing_run as S

mode = sys.argv[1]
S.MODE = mode
S.OUT_DIR = "quick_tp_" + mode
S.SMOKE = False
out = S.run_symbol(("SOL", 2025, "2025-01-01", "2026-01-01"))
print("RESULT", mode, out)

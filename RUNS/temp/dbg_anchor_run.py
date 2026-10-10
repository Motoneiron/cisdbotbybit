"""dbg_anchor_run.py — диагностика: свежий прогон ADA-2024 для tb и cb якорей рядом.

Вопрос: откуда расхождение наборов tf7e13_002 (tb) и tf7e13_cb, если оба, по коду,
берут slope_arr на одном и том же индексе? Проверяем на идентичном коде и данных.
"""
import logging as _log
import sys

sys.path.insert(0, r"D:\PYTHON\cisdbotbybit\RUNS\temp")
_log.disable(_log.CRITICAL)

import live_tf_grid as L  # noqa: E402

L.MODES["dbg_tb"] = {"profile": "tf7", "min_stop": 1.0, "sl_gate": (13, 0.0002, None, "tb")}
L.MODES["dbg_cb"] = {"profile": "tf7", "min_stop": 1.0, "sl_gate": (13, 0.0002, None, "cb")}
L.YEARS = [(2024, "2024-01-01", "2025-01-01")]
L.OUT_ROOT = r"D:\PYTHON\cisdbotbybit\RUNS\temp\dbg"

for m in ("dbg_tb", "dbg_cb"):
    L.MODE = m
    L.OUT_DIR = m
    msg = L.run_symbol("ADA")
    print(m, "->", msg, flush=True)
print("DBG_DONE", flush=True)

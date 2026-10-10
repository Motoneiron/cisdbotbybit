# test_dtfilter.py — проверка действия фильтра dt_sw_min: порог 999999 => n должно стать 0.
import sys
sys.path.insert(0, r"D:\PYTHON\cisdbotbybit\RUNS\temp")
import stop_timing_run as S

S.MODE = "tf1v2"
S.OUT_DIR = "test_dt999"
S.SMOKE = False
S.MODES["tf1v2"]["dt_sw_min"] = 999999
out = S.run_symbol(("ADA", 2024, "2024-06-01", "2024-07-01"))
print("RESULT(port 999999):", out)

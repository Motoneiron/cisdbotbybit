"""gate_2024_check.py — оценка slope-гейта по старым файлам tf7e13_002 (4 пары, 2024).

ВНИМАНИЕ: файлы из корня live_tf/ (до фикса OUT_DIR) — используются ТОЛЬКО как
быстрая прикидка эффекта гейта (n сверяется с логами tf7e13). Полные чистые
результаты будут в live_tf/tf7e13_002/ после перезапуска.
"""
import os

import pandas as pd

BASE = "live_tf"
pairs = ["KAS", "SOL", "DOGE", "ADA"]
expect_n = {"KAS": 118, "SOL": 101, "DOGE": 95, "ADA": 93}
tot_n = 0
tot_r = 0.0
print(f"{'пара':6}{'n':>6}{'ожид.':>7}{'ΣR':>9}{'avg':>9}")
for p in pairs:
    f = os.path.join(BASE, f"{p}_2024.pkl")
    rows = pd.read_pickle(f)
    df = pd.DataFrame(rows)
    n = len(df)
    sr = float(df["r"].sum())
    avg = sr / n if n else 0.0
    chk = "OK" if n == expect_n[p] else f"!! (ожид {expect_n[p]})"
    print(f"{p:6}{n:>6}{chk:>9}{sr:>+9.1f}{avg:>+9.3f}")
    tot_n += n
    tot_r += sr
print(f"{'ИТОГО 4 пары 2024':>20}: n={tot_n} ΣR={tot_r:+.1f} avg={tot_r/tot_n:+.3f}")
print()
print("Для сравнения: база ms1.0 2024 по ВСЕМ 6 парам: ΣR=+22 (таблица §7).")
print("Старые skip_gate в логах tf7e13: KAS 68, SOL ?, DOGE ?, ADA ? (см. tf7e13_out.txt)")

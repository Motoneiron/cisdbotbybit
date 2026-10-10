# Агрегатор QUICK-серии (SOL/2025): таблица по всем q_* режимам + база.
import os, pickle, sys
ROOT = r"D:\PYTHON\cisdbotbybit\RUNS\temp\live_tf"

def stats(path):
    if not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        rows = pickle.load(f)
    n = len(rows)
    sr = sum(r["r"] for r in rows)
    tp = sum(1 for r in rows if r["outcome"] == "tp")
    sl = sum(1 for r in rows if r["outcome"] == "sl")
    tm = sum(1 for r in rows if r["outcome"] == "time")
    return n, sr, tp, sl, tm

pairs = [
    ("BASE sp21 lc (tf1lc15_foff)", "tf1lc15_foff"),
    ("sp8 lc", "q_sp8_lc"),
    ("sp13 lc", "q_sp13_lc"),
    ("sp34 lc", "q_sp34_lc"),
    ("sp8 cb", "q_sp8_cb"),
    ("sp13 cb", "q_sp13_cb"),
    ("sp21 cb", "q_sp21_cb"),
    ("sp34 cb", "q_sp34_cb"),
    ("cc21", "q_cc21"),
    ("sw21", "q_sw21"),
    ("sw13", "q_sw13"),
    ("th0.01 lc", "q_th001"),
    ("th0.03 lc", "q_th003"),
    ("th0.05 lc", "q_th005"),
    ("th0.10 lc", "q_th010"),
    ("th0.05 cb", "q_th005_cb"),
    ("ss3 (smooth3) lc", "q_ss3"),
    ("ss5 (smooth5) lc", "q_ss5"),
    ("ss3 cb", "q_ss3_cb"),
    ("1D sp13 lc", "q_1d13"),
    ("8h sp13 lc", "q_8h13"),
    ("COMBO sp13 th0.03", "q_c13_003"),
    ("COMBO sp34 th0.03", "q_c34_003"),
    ("COMBO sp13 th0.05", "q_c13_005"),
    ("COMBO sp34 th0.05", "q_c34_005"),
]

print(f"{'mode':<22} {'n':>4} {'SR':>8} {'tp':>4} {'sl':>4} {'time':>4} {'WR%':>6} {'avgR':>7}")
tot = 0
for label, m in pairs:
    p = os.path.join(ROOT, m, "SOL_2025.pkl")
    s = stats(p)
    if s is None:
        print(f"{label:<22} MISSING ({m})")
        continue
    n, sr, tp, sl, tm = s
    wr = tp / n * 100 if n else 0
    avg = sr / n if n else 0
    print(f"{label:<22} {n:>4} {sr:>+8.2f} {tp:>4} {sl:>4} {tm:>4} {wr:>5.1f}% {avg:>+7.3f}")

# Матрица волны 3: финалисты × окна (SOL/2025).
import os, pickle
ROOT = r"D:\PYTHON\cisdbotbybit\RUNS\temp\live_tf"

def stats(m):
    p = os.path.join(ROOT, m, "SOL_2025.pkl")
    if not os.path.exists(p):
        return None
    with open(p, "rb") as f:
        rows = pickle.load(f)
    n = len(rows)
    sr = sum(r["r"] for r in rows)
    tp = sum(1 for r in rows if r["outcome"] == "tp")
    sl = sum(1 for r in rows if r["outcome"] == "sl")
    tm = sum(1 for r in rows if r["outcome"] == "time")
    return n, sr, tp, sl, tm

spec = [
    ("база sp21", "tf1lc15_foff", "tf1lc15_l1h", "q1h12_sp21"),
    ("sp13", "q_sp13_lc", "q1h16_sp13", "q1h12_sp13"),
    ("sp13x0.05", "q_c13_005", "q1h16_sp13x05", "q1h12_sp13x05"),
    ("th0.03 (sp21)", "q_th003", "q1h16_th003", "q1h12_th003"),
    ("sp34", "q_sp34_lc", "q1h16_sp34", "q1h12_sp34"),
    ("sp34x0.03", "q_c34_003", "q1h16_sp34x03", "q1h12_sp34x03"),
]

print("=== SR / n по окнам ===")
print(f"{'config':<14} | {'5h/16h':>12} | {'1h/16h':>12} | {'1h/12h':>12}")
for label, a, b, c in spec:
    def f(x):
        s = stats(x)
        return "MISS" if s is None else f"{s[1]:+6.2f}/{s[0]:>3}"
    print(f"{label:<14} | {f(a):>12} | {f(b):>12} | {f(c):>12}")

print()
print("=== tp/sl/time для 1ч-версий ===")
print(f"{'config':<14} | {'1h/16h (tp/sl/tm)':>22} | {'1h/12h (tp/sl/tm)':>22}")
for label, a, b, c in spec:
    def f(x):
        s = stats(x)
        return "MISS" if s is None else f"{s[2]}/{s[3]}/{s[4]}"
    print(f"{label:<14} | {f(b):>22} | {f(c):>22}")

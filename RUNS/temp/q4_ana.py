# Волна 4: кривая входа 15м/30м/45м/1ч/5ч (SOL/2025) + переходы при сужении.
import os, pickle
from collections import Counter
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

print("=== SR / n: кривая входа (выход 16ч) ===")
print(f"{'config':<10} | {'15m':>11} | {'30m':>11} | {'45m':>11} | {'1h':>11} | {'5h':>11}")
spec = [
    ("база sp21", "q15m_sp21", "q30m_sp21", "q45m_sp21", "tf1lc15_l1h", "tf1lc15_foff"),
    ("sp13", "q15m_sp13", "q30m_sp13", "q45m_sp13", "q1h16_sp13", "q_sp13_lc"),
    ("th0.03", "q15m_th003", "q30m_th003", "q45m_th003", "q1h16_th003", "q_th003"),
]
for rec in spec:
    label, *mods = rec
    def f(x):
        s = stats(x)
        return "MISS" if s is None else f"{s[1]:+6.2f}/{s[0]:>3}"
    print(f"{label:<10} | " + " | ".join(f(m) for m in mods))

def load(m):
    with open(os.path.join(ROOT, m, "SOL_2025.pkl"), "rb") as f:
        return {(r["scan"], r["direction"], r["cbt"]): r for r in pickle.load(f)}

def cmp(a, b):
    A, B = load(a), load(b)
    ka, kb = set(A), set(B)
    dropped, added = ka - kb, kb - ka
    sumA = sum(r["r"] for r in A.values())
    sumB = sum(r["r"] for r in B.values())
    def dsc(keys, D):
        c = Counter(D[k]["outcome"] for k in keys)
        s = sum(D[k]["r"] for k in keys)
        return len(keys), s, dict(c)
    n, s, c = dsc(dropped, A)
    n2, s2, c2 = dsc(added, B)
    print(f"{a} -> {b}: A {sumA:+.2f}/{len(A)}  B {sumB:+.2f}/{len(B)}  d={sumB - sumA:+.2f} | dropped n={n} SR={s:+.2f} {c} | added n={n2} SR={s2:+.2f} {c2}")

print()
print("=== Переходы sp13 при сужении входа ===")
cmp("q1h16_sp13", "q45m_sp13")
cmp("q45m_sp13", "q30m_sp13")
cmp("q30m_sp13", "q15m_sp13")
print()
print("=== Переходы базы при сужении входа ===")
cmp("tf1lc15_l1h", "q45m_sp21")
cmp("q45m_sp21", "q30m_sp21")
cmp("q30m_sp21", "q15m_sp21")
print()
print("=== th0.03 при сужении ===")
cmp("q1h16_th003", "q45m_th003")
cmp("q45m_th003", "q30m_th003")

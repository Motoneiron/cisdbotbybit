# Переходы волны 3: влияние окна входа 1ч и выхода 12ч (SOL/2025).
import os, pickle
from collections import Counter
ROOT = r"D:\PYTHON\cisdbotbybit\RUNS\temp\live_tf"

def load(m):
    with open(os.path.join(ROOT, m, "SOL_2025.pkl"), "rb") as f:
        return {(r["scan"], r["direction"], r["cbt"]): r for r in pickle.load(f)}

def dsc(keys, D):
    c = Counter(D[k]["outcome"] for k in keys)
    s = sum(D[k]["r"] for k in keys)
    return len(keys), s, dict(c)

def cmp(a, b):
    A, B = load(a), load(b)
    ka, kb = set(A), set(B)
    common, dropped, added = ka & kb, ka - kb, kb - ka
    sumA = sum(r["r"] for r in A.values())
    sumB = sum(r["r"] for r in B.values())
    print(f"### {a} -> {b}")
    print(f"A: n={len(A)} SR={sumA:+.2f}   B: n={len(B)} SR={sumB:+.2f}   d={sumB - sumA:+.2f}   common={len(common)}")
    n, s, c = dsc(dropped, A)
    print(f"dropped (были в A, нет в B): n={n} SR={s:+.2f} {c}")
    n, s, c = dsc(added, B)
    print(f"added (новые в B):           n={n} SR={s:+.2f} {c}")
    print()

print("===== ВОЛНА 3: разбор =====")
cmp("q_sp13_lc", "q1h16_sp13")     # sp13: вход 5ч -> 1ч
cmp("q_th003", "q1h16_th003")      # th0.03: вход 5ч -> 1ч
cmp("tf1lc15_foff", "tf1lc15_l1h") # база: вход 5ч -> 1ч
cmp("q1h16_sp13", "q1h12_sp13")    # sp13: выход 16ч -> 12ч

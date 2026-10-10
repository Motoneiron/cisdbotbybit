# Поштучные переходы между q-конфигами на SOL/2025: что режет/что добавляет гейт.
import os, pickle
from collections import Counter

ROOT = r"D:\PYTHON\cisdbotbybit\RUNS\temp\live_tf"

def load(m):
    p = os.path.join(ROOT, m, "SOL_2025.pkl")
    with open(p, "rb") as f:
        rows = pickle.load(f)
    return {(r["scan"], r["direction"], r["cbt"]): r for r in rows}

def sdesc(keys, D):
    c = Counter(D[k]["outcome"] for k in keys)
    s = sum(D[k]["r"] for k in keys)
    return len(keys), s, dict(c)

def top(keys, D, k=3, worst=True):
    rs = sorted(((D[x]["r"], x) for x in keys), key=lambda t: t[0])
    sel = rs[:k] if worst else rs[-k:]
    return ", ".join(f"{r:+.2f}({D[x]['direction'][0]})" for r, x in sel)

def cmp(a, b):
    A, B = load(a), load(b)
    ka, kb = set(A), set(B)
    common = ka & kb
    dropped = ka - kb
    added = kb - ka
    sumA = sum(r["r"] for r in A.values())
    sumB = sum(r["r"] for r in B.values())
    print(f"### {a}  ->  {b}")
    print(f"A: n={len(A)} SR={sumA:+.2f}    B: n={len(B)} SR={sumB:+.2f}    d={sumB - sumA:+.2f}")
    print(f"common={len(common)}  SR_common: A={sum(A[k]['r'] for k in common):+.2f} B={sum(B[k]['r'] for k in common):+.2f}")
    n, s, c = sdesc(dropped, A)
    print(f"dropped (были в A, выпали в B): n={n} SR={s:+.2f} {c}")
    if dropped:
        print(f"   худшие выпавшие: {top(dropped, A, 3, True)}")
    n, s, c = sdesc(added, B)
    print(f"added (новые в B):              n={n} SR={s:+.2f} {c}")
    if added:
        print(f"   лучшие новые:    {top(added, B, 3, False)}")
    ch = [k for k in common if abs(A[k]["r"] - B[k]["r"]) > 1e-9]
    print()

print("===== СРАВНЕНИЯ (SOL/2025) =====")
cmp("tf1lc15_foff", "q_sp13_lc")   # база -> спан13
cmp("tf1lc15_foff", "q_th005")     # база -> порог 0.05 (спан21)
cmp("q_sp13_lc", "q_c13_005")      # спан13 -> спан13+порог0.05
cmp("q_th005", "q_c13_005")        # порог0.05 (21) -> порог0.05 (13)
cmp("tf1lc15_foff", "q_c13_005")   # база -> финальный комбо

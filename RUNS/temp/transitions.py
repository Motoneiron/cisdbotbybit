"""transitions.py — переходы сделок между базой (foff = 5ч/16ч) и точками сеток hold/limit."""
import glob
import os
import pickle
from collections import defaultdict

BASE = r"D:\PYTHON\cisdbotbybit\RUNS\temp\live_tf"


def load(m):
    rows = []
    for f in sorted(glob.glob(os.path.join(BASE, m, "*.pkl"))):
        rows += pickle.load(open(f, "rb"))
    return rows


def key(r):
    return (r["sym"], str(r["scan"]), r["direction"], str(r.get("cbt") or ""))


def diff(base_rows, other_rows, name):
    print(f"### {name}")
    b, o = defaultdict(list), defaultdict(list)
    for r in base_rows:
        b[key(r)].append(r)
    for r in other_rows:
        o[key(r)].append(r)
    kb, ko = set(b), set(o)
    common, only_b, only_o = kb & ko, kb - ko, ko - kb
    ndup = sum(1 for k in b if len(b[k]) > 1) + sum(1 for k in o if len(o[k]) > 1)
    if ndup:
        print(f"  (дубли ключей: {ndup})")
    trans = defaultdict(lambda: [0, 0.0, 0.0])
    for k in common:
        rb, ro = b[k][0], o[k][0]
        slot = trans[(rb["outcome"], ro["outcome"])]
        slot[0] += 1
        slot[1] += float(rb["r"])
        slot[2] += float(ro["r"])
    for (a, bb), (n, sb, so) in sorted(trans.items()):
        print(f"  {a:>4s} -> {bb:<4s} n={n:4d}   SR_base={sb:+7.1f}  SR_new={so:+7.1f}  (d={so - sb:+7.1f})")

    def agg(keys, dd):
        n, sr, cats = 0, 0.0, defaultdict(int)
        for k in keys:
            r = dd[k][0]
            n += 1
            sr += float(r["r"])
            cats[r["outcome"]] += 1
        return n, sr, dict(cats)

    n, sr, cats = agg(only_b, b)
    print(f"  ТОЛЬКО-В-БАЗЕ: n={n} SR={sr:+.1f} {cats}")
    n, sr, cats = agg(only_o, o)
    print(f"  ТОЛЬКО-В-НОВОМ: n={n} SR={sr:+.1f} {cats}")
    print()


fb = load("tf1lc15_foff")
for m in ("tf1lc15_foff_h12", "tf1lc15_foff_h8", "tf1lc15_foff_h6"):
    diff(fb, load(m), m)
for m in ("tf1lc15_l2h", "tf1lc15_l1h", "tf1lc15_l30m", "tf1lc15_l15m"):
    diff(fb, load(m), m)

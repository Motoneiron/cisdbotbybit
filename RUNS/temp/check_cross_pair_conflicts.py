"""Масштаб: сколько сделок в бэке попадают в один (tf, htf-окно) у РАЗНЫХ пар.

Бэк симулирует пары независимо (лок per-pair), live-бот держит ОБЩИЙ htf_taken
(tf|окно). Оценка сверху: конфликтующие сделки после первой в окне live бы не взял.
"""
import glob
import pickle
import re
from collections import defaultdict

files = []
for pat in (r"D:/PYTHON/CISDBOT/RUNS/*/bot_aligned/*_tf*_202*.pkl",):
    files.extend(glob.glob(pat))

# берём последний файл на (sym, prof, year)
best = {}
for f in sorted(files, key=lambda p: p.replace("\\", "/")):
    name = f.replace("\\", "/").split("/")[-1]
    m = re.match(r"([A-Z]+)_(tf\d)_(\d{4})-\d{2}-\d{2}_.*\.pkl", name)
    if not m:
        continue
    sym, prof, year = m.groups()
    if int(year) not in (2024, 2025):
        continue
    best[(sym, prof, year)] = f

rows = defaultdict(list)  # (prof, htf) -> [(ts, sym, r)]
total = 0
for (sym, prof, year), f in best.items():
    c = pickle.load(open(f, "rb"))
    for t in c.get("trades") or []:
        if t.get("entry_kind") != "LIMIT":
            continue
        ht = str(t.get("htf_time") or "")
        if not ht:
            continue
        ts = None
        for k in ("entry_time", "fill_time"):
            if t.get(k):
                ts = str(t[k])
                break
        rows[(prof, ht)].append((ts or "", sym))
        total += 1

multi = {k: v for k, v in rows.items() if len(set(s for _, s in v)) > 1}
multi_n = sum(len(v) for v in multi.values())
lost = sum(len(v) - 1 for v in multi.values())
print(f"LIMIT-сделок всего: {total} в {len(rows)} окнах")
print(f"окон с 2+ РАЗНЫМИ парами: {len(multi)}; сделок в них: {multi_n}")
print(f"потенциально блокируемых live-локом (сверх первой в окне): {lost} = {100*lost/total:.1f}%")
for k, v in sorted(multi.items(), key=lambda kv: -len(kv[1]))[:8]:
    print(f"  {k[0]} {k[1]}: {len(v)} сделок: {sorted(set(s for _, s in v))}")

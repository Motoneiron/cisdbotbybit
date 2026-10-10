"""Агрегатор абляций tf7 (RUNS/temp/tf7_abl/*.pkl) — с учётом покрытия конфигов.

Полные конфиги (>=60 файлов) идут в сравнение; неполные — только статусом.
Вывод: MEXC/Bybit (все годы и 24-26), по годам, LONG/SHORT, контроль BASE vs C5.
"""
import glob
import os
import pickle
from collections import Counter

import pandas as pd

BASE = r"D:/PYTHON/cisdbotbybit/RUNS/temp"
ORDER = ("BASE_rerun", "ABL_FILT_OFF", "ABL_MSS_MAIN", "ABL_LIM30", "ABL_POS6H", "ABL_HTF8H")

cov = Counter()
for f in glob.glob(BASE + "/tf7_abl/*.pkl"):
    b = os.path.basename(f)
    for c in ORDER:
        if b.startswith(c):
            cov[c] += 1
            break
print("покрытие:", dict(cov))
FULL = {c for c, n in cov.items() if n >= 60}

rows = []
for f in glob.glob(BASE + "/tf7_abl/*.pkl"):
    rows.extend(pickle.load(open(f, "rb")))
d = pd.DataFrame(rows)
d = d[d.config.isin(FULL)]
d["year"] = d["year"].astype(int)
print("сделок в полных конфигах:", len(d))

def _fr(kind, outcome, spx, maker, taker):
    if not spx or spx <= 0:
        return 0.0
    e = maker if str(kind).upper() == "LIMIT" else taker
    x = maker if outcome == "tp" else taker
    return (e + x) / spx

d["r_byb"] = d["r_net_mexc"] + [
    _fr(k, o, s, 0.0006, 0.0008) - _fr(k, o, s, 0.00036, 0.0010)
    for k, o, s in zip(d.entry_kind, d.outcome, d.sp)
]

def stat(sub, col="r_net_mexc"):
    n = len(sub)
    if n == 0:
        return "n=0"
    m = sub[col].mean()
    se = sub[col].std(ddof=1) / n ** 0.5 if n > 1 else float("nan")
    t = m / se if se and se == se and se != 0 else float("nan")
    return f"n={n:>5} avg={m:+.4f} t={t:+.2f} Sum={sub[col].sum():+.1f}"

out = []
P = out.append
print("\n==== СВОДКА (полные конфиги) ====")
for cfg in ORDER:
    if cfg not in FULL:
        print(f"\n## {cfg}: НЕ ГОТОВ ({cov.get(cfg,0)}/67) — пропущен")
        continue
    q = d[d.config == cfg]
    lt = q[q.year >= 2024]
    print(f"\n## {cfg}")
    for lbl, sub, col in (("все ", q, "r_net_mexc"), ("24-26", lt, "r_net_mexc"),
                          ("Bybit все", q, "r_byb"), ("Bybit 24-26", lt, "r_byb")):
        line = f"  {lbl}: {stat(sub, col)}"
        print(line); P(line)

print("\n==== ПО ГОДАМ (Bybit) ====")
P("\n## ПО ГОДАМ (Bybit)")
for cfg in ORDER:
    if cfg not in FULL:
        continue
    q = d[d.config == cfg]
    line = f"{cfg:>12}: " + " | ".join(
        f"{y}:{stat(q[q.year == y], 'r_byb')}" for y in sorted(q.year.unique()))
    print(line); P(line)

print("\n==== LONG/SHORT (Bybit) ====")
P("\n## LONG/SHORT")
for cfg in ORDER:
    if cfg not in FULL:
        continue
    for lbl, sub in (("все", d[d.config == cfg]), ("24-26", d[(d.config == cfg) & (d.year >= 2024)])):
        line = f"{cfg:>12} [{lbl}]: " + " | ".join(
            f"{dr}: {stat(sub[sub.direction == dr], 'r_byb')}" for dr in ("LONG", "SHORT"))
        print(line); P(line)

print("\n==== КОНТРОЛЬ: BASE vs tf7_pairs C5 ====")
P("\n## КОНТРОЛЬ BASE vs C5")
try:
    old = []
    for f in glob.glob(BASE + "/tf7_pairs/C5_limit_1r_*.pkl"):
        old.extend(pickle.load(open(f, "rb")))
    od = pd.DataFrame(old)
    o24 = od[od.year.astype(int) >= 2024]
    b24 = d[(d.config == "BASE_rerun") & (d.year >= 2024)]
    line = f"  C5(24-26): {stat(o24)} | BASE(24-26): {stat(b24)}"
    print(line); P(line)
    oh = set(str(x) for x in od.hash)
    bh = set(str(x) for x in b24.hash)
    line = f"  общих хешей: {len(oh & bh)} из C5={len(oh)}"
    print(line); P(line)
except FileNotFoundError:
    print("  (нет tf7_pairs для сверки)")

open(BASE + "/tf7_abl_agg.txt", "w", encoding="utf-8").write("\n".join(out))
print("\nwritten:", BASE + "/tf7_abl_agg.txt")

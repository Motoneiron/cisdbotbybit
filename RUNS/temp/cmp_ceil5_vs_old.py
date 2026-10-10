"""Сверка: старый vs ceil5 (текущий) vs floor30 (вчерашний) — поштучно по SOL tf8 2024."""
import pickle

import pandas as pd

old_f = r"D:/PYTHON/CISDBOT/RUNS/2026-09-11/bot_aligned/SOL_tf8_2024-01-01_2024-12-31.pkl"
new_f = r"D:/PYTHON/CISDBOT/RUNS/2026-09-12/bot_aligned/SOL_tf8_2024-01-01_2024-12-31.pkl"
floor_f = r"D:/PYTHON/cisdbotbybit/RUNS/temp/sol_tf8_iso_floor30.pkl"

def load(f):
    c = pickle.load(open(f, "rb"))
    t = c.get("trades") or []
    return t

def key(t):
    return (str(t.get("entry_time") or t.get("entry_bar")), str(t.get("direction")), float(t.get("entry") or 0))

old = load(old_f)
new = load(new_f)
flo = load(floor_f)

print(f"old: {len(old)} | new(ceil5): {len(new)} | floor30: {len(flo)}")

# сравнение old vs new по entry_time
ko = {}
for t in old:
    ko.setdefault(str(t.get("entry_time")), []).append(t)
kn = {}
for t in new:
    kn.setdefault(str(t.get("entry_time")), []).append(t)

same_ts = set(ko) & set(kn)
only_old = set(ko) - set(kn)
only_new = set(kn) - set(ko)
print(f"entry_time: общих={len(same_ts)}, только old={len(only_old)}, только new={len(only_new)}")

# по created_bar/entry_bar фейки в new
fake_new = sum(1 for t in new if t.get("entry_bar") is not None and t.get("created_bar") is not None and t["entry_bar"] < t["created_bar"])
same_new = sum(1 for t in new if t.get("entry_bar") is not None and t.get("created_bar") is not None and t["entry_bar"] == t["created_bar"])
later_new = sum(1 for t in new if t.get("entry_bar") is not None and t.get("created_bar") is not None and t["entry_bar"] > t["created_bar"])
print(f"new: раньше={fake_new}, ровно={same_new}, позже={later_new}")

# первые 3 расхождения
for ts_ in sorted(only_old)[:3]:
    t = ko[ts_][0]
    print(f"  только old: {ts_} {t.get('direction')} entry={t.get('entry')} r={t.get('r_net')}")
for ts_ in sorted(only_new)[:3]:
    t = kn[ts_][0]
    print(f"  только new: {ts_} {t.get('direction')} entry={t.get('entry')} r={t.get('r_net')}")

# суммарные r_net по LIMIT
for label, ts in (("old", old), ("new", new), ("floor", flo)):
    lim = [t for t in ts if t.get("entry_kind") == "LIMIT"]
    print(f"{label}: LIMIT={len(lim)} sumR={sum(float(t.get('r_net') or 0) for t in lim):+.1f}")

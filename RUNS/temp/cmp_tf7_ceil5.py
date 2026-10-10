"""tf7 проверка + контроль: сравнение old vs ceil5 по tf7."""
import pickle

old_f = r"D:/PYTHON/CISDBOT/RUNS/2026-09-11/bot_aligned/SOL_tf7_2024-01-01_2024-12-31.pkl"
new_f = r"D:/PYTHON/CISDBOT/RUNS/2026-09-12/bot_aligned/SOL_tf7_2024-01-01_2024-12-31.pkl"

def load(f):
    c = pickle.load(open(f, "rb"))
    return c.get("trades") or []

old, new = load(old_f), load(new_f)
print(f"tf7 old: {len(old)} | new: {len(new)}")
for label, ts in (("old", old), ("new", new)):
    lim = [t for t in ts if t.get("entry_kind") == "LIMIT"]
    print(f"  {label}: LIMIT={len(lim)} sumR={sum(float(t.get('r_net') or 0) for t in lim):+.1f} "
          f"TP={sum(1 for t in lim if t['outcome']=='tp')} SL={sum(1 for t in lim if t['outcome']=='sl')}")

# множества differ по (created_bar, entry_bar, direction)
co = sorted((t.get("created_bar"), t.get("entry_bar"), t.get("direction")) for t in old if t.get("entry_kind")=="LIMIT")
cn = sorted((t.get("created_bar"), t.get("entry_bar"), t.get("direction")) for t in new if t.get("entry_kind")=="LIMIT")
print("одинаковые кортежи:", co == cn, f"(old {len(co)} / new {len(cn)})")
if co != cn:
    so, sn = set(co), set(cn)
    print("только old:", len(so-sn), "| только new:", len(sn-so))

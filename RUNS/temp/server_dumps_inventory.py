"""Инвентаризация серверных дампов сделок: символы, tf, месяцы, пересечение с 105 SOL."""
import json
from collections import Counter
from pathlib import Path

BASE = Path(r"D:/PYTHON/CISDBOT/.tmp_live_compare")
mine = json.load(open(r"D:/PYTHON/cisdbotbybit/RUNS/temp/live_recon/live_sol_tf7_trades.json", encoding="utf-8"))
mine_ids = {t["id"] for t in mine}
print("мои SOL-сделки (audit):", len(mine_ids))

def sym(px):
    return "SOL" if 0 < px < 1000 else "BTC"

for f in ("server_trades_20260722.json", "server_trades_now.json", "server_trades_pre_20260603.json"):
    d = json.load(open(BASE / f, encoding="utf-8"))
    syms, tfs, months = Counter(), Counter(), Counter()
    ids = set()
    for t in d:
        px = float(t.get("entry_price") or 0)
        syms[sym(px)] += 1
        tfs[str(t.get("tf"))] += 1
        months[str(t.get("entry_time"))[:7]] += 1
        ids.add(str(t.get("id")))
    inter = ids & mine_ids
    print(f"\n{f}: n={len(d)}")
    print("  символы:", dict(syms), "| tf:", dict(tfs))
    print("  месяцы:", dict(sorted(months.items())))
    print("  пересечение с моими 105:", len(inter))

# отдельно: SOL-сделки в 'now' — какой период
d = json.load(open(BASE / "server_trades_now.json", encoding="utf-8"))
sol = [t for t in d if 0 < float(t.get("entry_price") or 0) < 1000]
print(f"\nSOL-сделок в server_trades_now: {len(sol)}")
if sol:
    dm = Counter(str(t.get("entry_time"))[:7] for t in sol)
    print("  по месяцам:", dict(sorted(dm.items())))
    print("  пример:", {k: sol[0].get(k) for k in ("id", "direction", "entry_price", "entry_time", "exit_time")})
    # есть ли статусы?
    st = Counter(str(t.get("status") or t.get("exit_reason") or "?") for t in sol)
    print("  статусы/исходы:", dict(st.most_common(8)))
    keys = sorted(sol[0].keys())
    print("  поля:", keys)

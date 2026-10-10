"""Состав сентябрьских выгрузок: сколько SOL tf7 closed всего (по всем источникам)."""
import json
from collections import Counter
from pathlib import Path

mine = {t["id"]: t for t in json.load(open(r"D:/PYTHON/cisdbotbybit/RUNS/temp/live_recon/live_sol_tf7_trades.json", encoding="utf-8"))}

def sym(px):
    return "SOL" if 0 < px < 1000 else "BTC"

# 1) srv_trades.json (cisdbotbybit) — уже видел: 11 (6 tf7, 5 tf8)
srv = json.load(open(r"D:/PYTHON/cisdbotbybit/RUNS/temp/srv_trades.json", encoding="utf-8"))
print("srv_trades.json:")
for t in srv:
    print(f"   {t.get('id')} tf={t.get('tf')} {t.get('direction')} {str(t.get('entry_time'))[:16]} "
          f"entry={t.get('entry_price')} {t.get('status')} kind={t.get('entry_kind')}")

# 2) trades_2026-09.jsonl (cisdbotbybit/RUNS/temp) — события
p = Path(r"D:/PYTHON/cisdbotbybit/RUNS/temp/trades_2026-09.jsonl")
ev = Counter()
closed = {}
for line in p.read_text(encoding="utf-8").splitlines():
    if not line.strip():
        continue
    try:
        r = json.loads(line)
    except json.JSONDecodeError:
        continue
    ev[str(r.get("event"))] += 1
    if r.get("event") == "closed":
        rid = str(r.get("id"))
        px = float(r.get("entry_price") or r.get("signal_entry") or 0)
        if 0 < px < 1000 and str(r.get("tf")) == "tf7":
            closed[rid] = r
print("\ntrades_2026-09.jsonl события:", dict(ev))
print("closed SOL tf7:", len(closed), "| пересечение с моими:", len(set(closed) & set(mine)))
for rid, r in sorted(closed.items(), key=lambda kv: str(kv[1].get("exit_time"))):
    new = "" if rid in mine else "  <-- НОВАЯ"
    print(f"   {rid} {r.get('direction')} entry={str(r.get('entry_time'))[:16]} exit={str(r.get('exit_time'))[:16]} "
          f"{r.get('exit_reason')} px={r.get('entry_price')}{new}")

# 3) live_journal_09.jsonl
p2 = Path(r"D:/PYTHON/cisdbotbybit/RUNS/temp/live_journal_09.jsonl")
ev2 = Counter()
closed2 = {}
for line in p2.read_text(encoding="utf-8", errors="replace").splitlines():
    if not line.strip():
        continue
    try:
        r = json.loads(line)
    except json.JSONDecodeError:
        continue
    ev2[str(r.get("event"))] += 1
    if r.get("event") == "closed":
        rid = str(r.get("id"))
        px = float(r.get("entry_price") or r.get("signal_entry") or 0)
        if 0 < px < 1000 and str(r.get("tf")) == "tf7":
            closed2[rid] = r
print("\nlive_journal_09.jsonl события:", dict(ev2))
print("closed SOL tf7:", len(closed2), "| пересечение с моими:", len(set(closed2) & set(mine)),
      "| пересечение с trades_2026-09:", len(set(closed2) & set(closed)))

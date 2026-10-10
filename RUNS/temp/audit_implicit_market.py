"""Классификация филлов: «цена уже за уровнем в момент создания лимитки» (неявный MARKET).

Смотрим журнал trade_logs/*.jsonl: пары pending_created -> entry_filled.
Для LONG: неявный MARKET, если price_at_creation <= entry (уровень уже позади/выше рынка).
Для SHORT: зеркально (price_at_creation >= entry).
Для таких лимитка на бирже исполнилась бы сразу по рынку, а бот пишет филл по цене уровня.
Плюс: сколько времени прошло от создания до филла.
"""
import json
import glob
from pathlib import Path

BASE = Path("/opt/cisdbotbybit")
pend = {}
filled = {}
for f in sorted(glob.glob(str(BASE / "trade_logs" / "trades_*.jsonl"))):
    for line in open(f, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        ev = r.get("event")
        if ev == "pending_created":
            pend[r["id"]] = r
        elif ev == "entry_filled":
            filled[r["id"]] = r


def ts(s):
    import datetime as dt
    try:
        return dt.datetime.fromisoformat(str(s))
    except Exception:
        return None


def beyond(direction, entry, price):
    if not entry or not price:
        return None
    return price <= entry if direction == "LONG" else price >= entry


rows = []
for pid, p in pend.items():
    fl = filled.get(pid)
    entry = float(p.get("signal_entry") or p.get("entry_price") or 0)
    pac = float(p.get("price_at_creation") or 0)
    b = beyond(p.get("direction"), entry, pac)
    dt_s = None
    if fl:
        a, c = ts(p.get("pending_created_at") or p.get("logged_at")), ts(fl.get("entry_time"))
        if a and c:
            dt_s = (c - a).total_seconds()
    rows.append({
        "id": pid, "sym": p.get("symbol"), "tf": p.get("tf"), "dir": p.get("direction"),
        "entry": entry, "pac": pac, "beyond": b, "filled": bool(fl),
        "dt_fill_s": round(dt_s, 1) if dt_s is not None else None,
        "created": str(p.get("pending_created_at"))[:19],
        "status": p.get("status") if not fl else None,
    })

rows.sort(key=lambda r: r["created"])
print("всего лимиток в журнале:", len(rows), "| из них с филлом:", sum(1 for r in rows if r["filled"]))
bad_all = [r for r in rows if r["beyond"]]
bad_f = [r for r in rows if r["beyond"] and r["filled"]]
print("«цена уже за уровнем» на момент создания:", len(bad_all), "| из них заполнено:", len(bad_f))
print("из заполненных «за уровнем» — филл быстрее 60 c:", sum(1 for r in bad_f if (r["dt_fill_s"] or 999) < 60))
print()
print("--- все случаи «за уровнем» ---")
for r in bad_all:
    print(f"{r['created']} {r['sym']:5s} {r['tf']} {r['dir']:5s} entry={r['entry']} pac={r['pac']} "
          f"beyond={r['beyond']} filled={r['filled']} dt_fill={r['dt_fill_s']}s status={r['status']}")

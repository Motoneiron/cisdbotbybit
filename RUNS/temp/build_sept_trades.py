"""Сбор сентябрьских серверных tf7-сделок (мультипар) + цены пар для маппинга."""
import json
from collections import Counter
from pathlib import Path

T = Path(r"D:/PYTHON/cisdbotbybit/RUNS/temp")
rows = {}

# 1) srv_trades.json (с symbol_key)
for t in json.load(open(T / "srv_trades.json", encoding="utf-8")):
    if str(t.get("tf")) == "tf7":
        rows[str(t["id"])] = {
            "id": t["id"], "sym": t.get("symbol_key"), "direction": t.get("direction"),
            "entry_time": t.get("entry_time"), "exit_time": t.get("exit_time"),
            "entry_price": t.get("entry_price"), "sig_hash": t.get("sig_hash"),
            "htf_time": t.get("htf_time"), "status": t.get("status"),
            "entry_kind": t.get("entry_kind"), "source": "srv_trades",
        }

# 2) trades_2026-09.jsonl и live_journal_09.jsonl
for f in ("trades_2026-09.jsonl", "live_journal_09.jsonl"):
    for line in (T / f).read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("event") != "closed" or str(r.get("tf")) != "tf7":
            continue
        rid = str(r.get("id"))
        if rid in rows:
            continue
        rows[rid] = {
            "id": rid, "sym": r.get("symbol_key"), "direction": r.get("direction"),
            "entry_time": r.get("entry_time"), "exit_time": r.get("exit_time"),
            "entry_price": r.get("entry_price"), "sig_hash": r.get("sig_hash"),
            "htf_time": r.get("htf_time"), "status": r.get("exit_reason"),
            "entry_kind": r.get("entry_kind"), "source": f,
        }

print("уникальных tf7-сделок:", len(rows))
months = Counter(str(v["entry_time"])[:7] for v in rows.values())
print("месяцы:", dict(sorted(months.items())))
print("по источникам:", dict(Counter(v["source"] for v in rows.values())))
print("с symbol_key:", sum(1 for v in rows.values() if v["sym"]))

# последние цены пар (для маппинга без symbol_key)
print("\nпоследние close по парам (data_recent):")
prices = {}
for p in ("BTC", "ETH", "DOGE", "KAS", "ADA", "BNB", "LINK", "LTC", "XRP", "SOL"):
    fp = T / f"data_recent/{p}USDT_5m_recent.csv"
    try:
        last = fp.read_text(encoding="utf-8", errors="replace").strip().splitlines()[-1]
        parts = last.split(",")
        px = float(parts[4]) if len(parts) > 4 else None
        prices[p] = px
        print(f"   {p}: {px}")
    except Exception as e:
        print(f"   {p}: ERR {e}")

def guess_sym(v, prices):
    if v["sym"]:
        return v["sym"]
    ep = float(v.get("entry_price") or 0)
    best, bd = None, 1e18
    for p, px in prices.items():
        if not px:
            continue
        d = abs(ep - px) / px
        if d < bd:
            bd, best = d, p
    return best if bd < 0.3 else "?"

for v in rows.values():
    v["sym_guess"] = guess_sym(v, prices)

print("\nпо парам (после маппинга):", dict(Counter(v["sym_guess"] for v in rows.values())))
print("\nсписок:")
for rid, v in sorted(rows.items(), key=lambda kv: str(kv[1]["entry_time"])):
    print(f"   {rid} {v['sym_guess']:>4} {v['direction']:>5} entry={str(v['entry_time'])[:16]} "
          f"px={v['entry_price']} htf={v['htf_time']} {v['status']} src={v['source'][:12]}")

out = T / "live_recon/sept_tf7_trades.json"
out.write_text(json.dumps(list(rows.values()), ensure_ascii=False, indent=1), encoding="utf-8")
print("\nwritten:", out)

"""Извлечь живые SOL tf7 сделки (closed) из live-логов в единый JSON.

Источник: .tmp_live_compare/audit_20260822/trades_2026-{06,07,08}.jsonl
Выход: live_recon/live_sol_tf7_trades.json
"""
import json
from pathlib import Path

SRC = Path(r"D:/PYTHON/CISDBOT/.tmp_live_compare/audit_20260822")
OUT = Path(r"D:/PYTHON/cisdbotbybit/RUNS/temp/live_recon")
OUT.mkdir(parents=True, exist_ok=True)

def symbol(row):
    px = float(row.get("entry_price") or row.get("signal_entry") or 0)
    return "SOL" if 0 < px < 1000 else "BTC"

def enrich(r):
    e = float(r.get("entry_price") or 0)
    st = float(r.get("stop") or 0)
    tp = float(r.get("tp") or 0)
    contracts = float(r.get("contracts") or 0)
    cv = 0.1 if symbol(r) == "SOL" else 0.0001
    risk = abs(e - st) * contracts * cv
    net = float(r.get("pnl_net") or 0)
    gross = float(r.get("pnl") or 0)
    return {
        "id": r.get("id"), "symbol": symbol(r), "tf": r.get("tf"),
        "direction": r.get("direction"), "category": r.get("category"),
        "entry_kind": r.get("entry_kind"),
        "signal_time": r.get("signal_time"), "trigger_bar_at": r.get("trigger_bar_at"),
        "entry_time": r.get("entry_time"), "exit_time": r.get("exit_time"),
        "entry_price": e, "signal_entry": r.get("signal_entry"),
        "stop": st, "tp": tp, "cisd_level": r.get("cisd_level"),
        "sweep_level": r.get("sweep_level"), "fib_1x": r.get("fib_1x"),
        "sig_hash": r.get("sig_hash"), "exit_reason": r.get("exit_reason"),
        "pnl": gross, "fees": float(r.get("fees") or 0), "pnl_net": net,
        "net_r": (net / risk) if risk > 0 else None,
        "planned_rr": (abs(tp - e) / abs(e - st)) if e and st and tp and e != st else None,
        "hold_h": None, "quality_score": r.get("quality_score"),
    }

events_by_file = {}
all_events = []
for name in ("trades_2026-06.jsonl", "trades_2026-07.jsonl", "trades_2026-08.jsonl"):
    p = SRC / name
    n = 0
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        n += 1
        all_events.append(row)
    events_by_file[name] = n
print("файлы:", events_by_file, "| всего строк:", len(all_events))

by_id = {}
for row in all_events:
    if row.get("event") != "closed" or row.get("mode") != "live":
        continue
    rid = str(row.get("id") or "")
    if rid:
        by_id[rid] = row

trades = [enrich(r) for r in by_id.values()]
sol = [t for t in trades if t["symbol"] == "SOL" and t["tf"] == "tf7"]
sol.sort(key=lambda t: str(t["exit_time"] or ""))
print("closed всего:", len(trades), "| SOL tf7:", len(sol))

# уточнить hold_h
from datetime import datetime
for t in sol:
    try:
        t["hold_h"] = (datetime.fromisoformat(t["exit_time"]) - datetime.fromisoformat(t["entry_time"])).total_seconds() / 3600
    except Exception:
        pass

tot_r = sum(t["net_r"] for t in sol if t["net_r"] is not None)
tp = sum(str(t["exit_reason"]).endswith("tp") for t in sol)
sl = sum(str(t["exit_reason"]).endswith("sl") for t in sol)
print(f"период: {sol[0]['entry_time'][:16]} -> {sol[-1]['exit_time'][:16]}")
print(f"tp={tp} sl={sl} other={len(sol)-tp-sl} | sum net_r = {tot_r:+.2f}")
kinds = {}
for t in sol:
    kinds[t["entry_kind"]] = kinds.get(t["entry_kind"], 0) + 1
print("kinds:", kinds)

(OUT / "live_sol_tf7_trades.json").write_text(
    json.dumps(sol, ensure_ascii=False, indent=1), encoding="utf-8")
print("written:", OUT / "live_sol_tf7_trades.json")

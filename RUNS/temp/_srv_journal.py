import json
from collections import Counter
p = "/opt/cisdbotbybit/trade_logs/trades_2026-09.jsonl"
rows = [json.loads(l) for l in open(p) if l.strip()]
print("N", len(rows), Counter(r.get("event") for r in rows))
for r in rows:
    ev = r.get("event")
    if ev == "signal_skipped":
        cat = r.get("category")
        if cat not in ("skipped_min_stop", "skipped_tp_already_hit", "skipped_sweep_invalid"):
            print("OTHER SKIP", cat)
        continue
    sym = None
    reason = r.get("skip_reason") or r.get("exit_reason") or ""
    # symbol from text
    blob = json.dumps(r, ensure_ascii=False)
    for s in ("SOL", "DOGE", "KAS", "ADA", "LINK", "LTC"):
        if s in blob:
            sym = s
            break
    print(
        ev, r.get("logged_at"), sym, r.get("direction"),
        "entry", r.get("entry_price") or r.get("signal_entry"),
        "stop", r.get("stop"), "tp", r.get("tp"),
        r.get("exit_reason") or r.get("category") or "",
        "htf", r.get("htf_time"), "sig", r.get("signal_time"),
    )

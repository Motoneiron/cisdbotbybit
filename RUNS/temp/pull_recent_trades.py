import json, os
from datetime import datetime, timedelta, timezone

D = "/opt/cisdbotbybit"
now = datetime.now(timezone.utc).replace(tzinfo=None)
cut = now - timedelta(hours=72)
cut19 = cut.strftime("%Y-%m-%d %H:%M:%S")
print("now_utc=%s cut=%s" % (now.strftime("%Y-%m-%d %H:%M:%S"), cut19))

def load(p):
    try:
        with open(os.path.join(D, p)) as f:
            return json.load(f)
    except Exception as e:
        print("load %s: %s" % (p, e))
        return None

def t19(s):
    return str(s)[:19] if s else ""

pos = load("shadow_positions.json")
pos = pos if isinstance(pos, list) else (pos or {}).get("positions", [])
print("positions total:", len(pos))
recent = [p for p in pos if t19(p.get("entry_time")) >= cut19]
print("recent(72h) positions:", len(recent))
if recent:
    print("POS KEYS:", sorted(recent[-1].keys()))
for p in recent:
    print("POS |", " | ".join([
        str(p.get("symbol_key")), str(p.get("direction")), str(p.get("tf")), str(p.get("status")),
        "e=%s" % p.get("entry_price"), "stop=%s" % (p.get("stop_price") or p.get("stop")),
        "created=%s" % t19(p.get("pending_created_at") or p.get("created_at")),
        "entry=%s" % t19(p.get("entry_time")), "exitpl=%s" % t19(p.get("exit_time")),
    ]))

tr = load("shadow_trades.json")
tr = tr if isinstance(tr, list) else (tr or {}).get("trades", [])
rect = [t for t in tr if t19(t.get("entry_time")) >= cut19]
print("closed trades recent(72h):", len(rect), "of total", len(tr))
if rect:
    print("TR KEYS:", sorted(rect[-1].keys()))
for t in rect:
    print("TR  |", " | ".join([
        str(t.get("symbol_key")), str(t.get("direction")), str(t.get("tf")), str(t.get("status")),
        "e=%s" % t.get("entry_price"), "c=%s" % t.get("close_price"), "pnl=%s" % t.get("pnl_net"),
        "entry=%s" % t19(t.get("entry_time")), "exitpl=%s" % t19(t.get("exit_time")),
    ]))

fn = os.path.join(D, "trade_logs", "trades_%s.jsonl" % now.strftime("%Y-%m"))
try:
    evs = [json.loads(l) for l in open(fn).read().splitlines() if l.strip()]
except Exception as e:
    evs = []
    print("jsonl: %s" % e)
evr = [e for e in evs if t19(e.get("ts")) >= cut19]
print("jsonl events recent(72h):", len(evr), "of total", len(evs))
if evr:
    print("EV KEYS:", sorted(evr[-1].keys()))
from collections import Counter
print("EV types:", Counter(e.get("event") for e in evr))
for e in evr:
    if e.get("event") in ("closed", "signal_skipped", "pending_cancelled", "pending_created", "filled"):
        print("EV  |", t19(e.get("ts")), e.get("event"), str(e.get("symbol_key")), str(e.get("direction")), str(e.get("tf")),
              "| r=%s" % e.get("r_net"), "| exit=%s" % (e.get("exit_reason") or e.get("cancel_reason") or e.get("reason")),
              "| px=%s" % (e.get("exit_price") or e.get("price")))

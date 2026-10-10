"""Полный список позиций (защита от None) + детали странных записей."""
import json

d = json.load(open("/opt/cisdbotbybit/shadow_positions.json"))
positions = d["positions"] if isinstance(d, dict) else d
print(f"всего: {len(positions)}")
print(f"{'sym':6} {'tf':4} {'dir':5} {'entry_time':16} | status       | pnl_net")
for p in sorted(positions, key=lambda x: str(x.get("entry_time"))):
    et = str(p.get("entry_time"))[:16]
    sk = str(p.get("symbol_key"))[:6]
    tf = str(p.get("tf"))[:4]
    status = str(p.get("status"))
    pnl = float(p["pnl_net"]) if p.get("pnl_net") is not None else 0.0
    print(f"{sk:6} {tf:4} {p['direction']:5} {et:16} | {status:12} | {pnl:+.2f}")

print("\n=== детали записей 2026-09-14 ===")
for p in sorted(positions, key=lambda x: str(x.get("entry_time"))):
    if str(p.get("entry_time", "")) >= "2026-09-14":
        print(json.dumps({k: p.get(k) for k in ("id", "symbol_key", "tf", "direction", "entry_time",
                                                "signal_entry", "close_price", "status", "pnl_net",
                                                "sig_hash", "htf_time", "signal_category")},
                         ensure_ascii=False, default=str))

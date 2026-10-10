"""Полный список SHADOW-позиций + последние события из лога."""
import json

d = json.load(open("/opt/cisdbotbybit/shadow_positions.json"))
positions = d["positions"] if isinstance(d, dict) else d
print(f"{'sym':5} {'tf':4} {'dir':5} {'entry_time':16} | status       | pnl_net | close_time")
for p in sorted(positions, key=lambda x: str(x.get("entry_time"))):
    et = str(p.get("entry_time"))[:16]
    ct = str(p.get("close_time") or p.get("closed_at") or "")[:16]
    print(f"{p.get('symbol_key'):5} {p.get('tf'):4} {p['direction']:5} {et:16} | {p['status']:12} | "
          f"{(float(p['pnl_net']) if p.get('pnl_net') is not None else 0):+.2f}  | {ct}")

print("\nпоследние 14 закрытий (для сверки):")
cl = [p for p in positions if str(p.get("status", "")).startswith("closed")]
for p in sorted(cl, key=lambda x: str(x.get("entry_time")))[-14:]:
    print(f"  {str(p.get('entry_time'))[:16]} {p.get('symbol_key')} {p.get('tf')} {p['direction']} "
          f"→ {p['status']} {float(p.get('pnl_net') or 0):+.2f}")

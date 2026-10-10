"""Детали: SOL-сделки дампа вне моих 105; BTC-разбивка; серверные логи vs audit."""
import json
from collections import Counter
from pathlib import Path

BASE = Path(r"D:/PYTHON/CISDBOT/.tmp_live_compare")
mine = {t["id"]: t for t in json.load(open(r"D:/PYTHON/cisdbotbybit/RUNS/temp/live_recon/live_sol_tf7_trades.json", encoding="utf-8"))}

now = json.load(open(BASE / "server_trades_now.json", encoding="utf-8"))
sol = [t for t in now if 0 < float(t.get("entry_price") or 0) < 1000]
btc = [t for t in now if float(t.get("entry_price") or 0) >= 1000]

print("SOL по tf:", dict(Counter(t["tf"] for t in sol)))
print("BTC по tf:", dict(Counter(t["tf"] for t in btc)))
print("BTC по месяцам:", dict(sorted(Counter(str(t.get("entry_time"))[:7] for t in btc).items())))

dump_ids = {str(t["id"]) for t in sol}
new_sol = [t for t in sol if str(t["id"]) not in mine]
print(f"\nSOL-сделки дампа, которых НЕТ в моих 105: {len(new_sol)}")
for t in sorted(new_sol, key=lambda x: str(x.get("entry_time"))):
    print(f"   {t['id']} {t['tf']} {t['direction']} {str(t.get('entry_time'))[:16]} {t.get('status')} "
          f"entry={t.get('entry_price')} kind={t.get('entry_kind')} cat={t.get('signal_category')}")

miss = [m for m in mine if m not in dump_ids]
print(f"\nмои 105, которых нет в дампе (идут после 15.08): {len(miss)}")
for m in miss:
    t = mine[m]
    print(f"   {m} {t['direction']} {str(t.get('entry_time'))[:16]} {t.get('exit_reason')}")

# серверные jsonl-логи: считаем SOL tf7 closed-события
logs = ["server_trade_logs_2026-06.jsonl", "server_trade_logs_2026-07.jsonl",
        "server_trade_logs_2026-07_fresh.jsonl", "server_trade_logs_2026-08.jsonl"]
all_ids = {}
for f in logs:
    n = 0
    ids = set()
    for line in (BASE / f).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        n += 1
        if r.get("event") == "closed" and r.get("mode") == "live":
            px = float(r.get("entry_price") or r.get("signal_entry") or 0)
            if 0 < px < 1000 and str(r.get("tf")) == "tf7":
                ids.add(str(r.get("id")))
    all_ids[f] = ids
    print(f"\n{f}: строк={n} | closed SOL tf7 ids={len(ids)}")
union = set().union(*all_ids.values())
print("\nобъединение по всем серверным логам:", len(union))
myids = set(mine)
print("пересечение с моими 105:", len(union & myids), "| только в серверных логах:", len(union - myids))
for i in sorted(union - myids)[:20]:
    print("   серверный лог, нет у меня:", i)

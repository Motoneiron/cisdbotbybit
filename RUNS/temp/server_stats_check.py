"""Разбор server_stats_2026-08-26 (выгрузка 25-26.08) + srv_trades.json (13.09)."""
import json
from collections import Counter

mine = {t["id"]: t for t in json.load(open(r"D:/PYTHON/cisdbotbybit/RUNS/temp/live_recon/live_sol_tf7_trades.json", encoding="utf-8"))}
print("мои 105 SOL tf7:", len(mine))


def sym(px):
    return "SOL" if 0 < px < 1000 else "BTC"


def looks_like_trades(d):
    if isinstance(d, list) and d and isinstance(d[0], dict) and "direction" in d[0]:
        return True
    return False


def describe(d, name):
    if looks_like_trades(d):
        syms = Counter(sym(float(t.get("entry_price") or 0)) for t in d)
        tfs = Counter(str(t.get("tf")) for t in d)
        months = Counter(str(t.get("entry_time"))[:7] for t in d)
        ids = {str(t.get("id")) for t in d}
        print(f"\n{name}: list trades n={len(d)}")
        print("  символы:", dict(syms), "| tf:", dict(tfs))
        print("  месяцы:", dict(sorted(months.items())))
        print("  пересечение с моими:", len(ids & set(mine)))
        new = sorted(ids - set(mine))
        if new:
            print("  НОВЫЕ id:", new[:20])
        # последние по времени
        last = sorted(d, key=lambda t: str(t.get("entry_time")))[-3:]
        for t in last:
            print("   хвост:", str(t.get("entry_time"))[:16], t.get("direction"), t.get("entry_price"), t.get("tf"), t.get("status") or t.get("exit_reason"))
    elif isinstance(d, dict):
        print(f"\n{name}: dict keys={list(d.keys())[:15]}")
        for k in list(d.keys())[:4]:
            print("   ", k, "->", str(d[k])[:120])
    else:
        print(f"\n{name}: {type(d)} n={len(d) if hasattr(d, '__len__') else '-'}")
        if d:
            print("   [0]:", str(d[0])[:200])


d = json.load(open(r"D:/PYTHON/CISDBOT/server_stats_2026-08-26/trades.json", encoding="utf-8"))
describe(d, "server_stats/trades.json")

try:
    sc = json.load(open(r"D:/PYTHON/CISDBOT/server_stats_2026-08-26/signals_cache.json", encoding="utf-8"))
    if isinstance(sc, list) and sc:
        print("\nsignals_cache: list n=", len(sc))
        print("  [0]:", str(sc[0])[:220])
        print("  [-1]:", str(sc[-1])[:220])
    else:
        describe(sc, "signals_cache.json")
except Exception as e:
    print("signals_cache ERR", e)

try:
    srv = json.load(open(r"D:/PYTHON/cisdbotbybit/RUNS/temp/srv_trades.json", encoding="utf-8"))
    describe(srv, "cisdbotbybit/srv_trades.json")
except Exception as e:
    print("srv_trades ERR", e)

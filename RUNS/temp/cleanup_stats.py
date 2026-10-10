"""Классификация сделок в shadow_trades.json по гейтам
A: неявный MARKET, B: свип окна, C: 30m-подтверждение,
D: триггер не обновил предыдущий в том же окне (лок пересвипа).

Запуск:  venv/bin/python3 /tmp/cleanup_stats.py            # dry-run (только таблица)
         venv/bin/python3 /tmp/cleanup_stats.py --apply    # правка файлов + отчёт
"""
import glob
import json
import shutil
import sys
import datetime as dt
from collections import defaultdict
from pathlib import Path

import ccxt
import pandas as pd

sys.path.insert(0, "/opt/cisdbotbybit")
import cisdbot as B   # noqa: E402

BASE = Path("/opt/cisdbotbybit")
APPLY = "--apply" in sys.argv
HTF_RATIO = 480
TZ = dt.timezone.utc
ex = ccxt.bybit({"enableRateLimit": True})

# trigger_bar_at из журнала (в записях позиций его нет)
trig = {}
for f in sorted(glob.glob(str(BASE / "trade_logs" / "trades_*.jsonl"))):
    for line in open(f, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get("id") and r.get("trigger_bar_at"):
            trig[r["id"]] = str(r["trigger_bar_at"])

cache = {}


def df30(sym):
    if sym not in cache:
        o = ex.fetch_ohlcv(f"{sym}/USDT:USDT", "30m", limit=1000)
        d = pd.DataFrame(o, columns=["t", "open", "high", "low", "close", "volume"])
        d["ts"] = pd.to_datetime(d["t"], unit="ms", utc=True).dt.tz_localize(None)
        cache[sym] = d.set_index("ts")[["open", "high", "low", "close", "volume"]]
    return cache[sym]


def _trig_ext(df, trig_s, long):
    if not trig_s:
        return None
    try:
        ts = pd.Timestamp(str(trig_s))
    except Exception:
        return None
    if ts not in df.index:
        return None
    row = df.loc[ts]
    if hasattr(row, "iloc") and getattr(row, "ndim", 1) > 1:
        row = row.iloc[0]
    return float(row["low"] if long else row["high"])


trades = json.load(open(BASE / "shadow_trades.json", encoding="utf-8"))
pos_list = json.load(open(BASE / "shadow_positions.json", encoding="utf-8"))
pos = {p["id"]: p for p in pos_list}

rows = []
for t in trades:
    pid = t["id"]
    p = pos.get(pid, {})
    sym = p.get("symbol_key") or t.get("symbol_key") or "SOL"
    d = t["direction"]
    long = d == "LONG"
    cisd = float(t.get("cisd_level") or t.get("signal_entry") or 0)
    sweep = float(t.get("sweep_level") or 0)
    htf = str(t.get("htf_time") or "")
    trig_s = str(trig.get(pid) or p.get("trigger_bar_at") or "")
    df = df30(sym)

    a_ok = B._is_retrace_at_creation(d, cisd, float(t.get("price_at_creation") or 0))
    b_ok, b_why = B._sweep_valid_for_setup(df, HTF_RATIO, htf, trig_s, sweep, d)

    created = pd.Timestamp(str(t.get("pending_created_at") or t.get("entry_time")))
    win0 = max(pd.Timestamp(htf), pd.Timestamp(trig_s)) if trig_s else pd.Timestamp(htf)
    win1 = pd.Timestamp(htf) + pd.Timedelta(minutes=HTF_RATIO)
    c_ok = c_win = False
    for tsx, row in df.iterrows():
        if tsx < win0 or tsx >= win1:
            continue
        beyond = (float(row["close"]) > cisd) if long else (float(row["close"]) < cisd)
        if not beyond:
            continue
        c_win = True
        if tsx + pd.Timedelta(minutes=30) <= created:
            c_ok = True

    rows.append({
        "id": pid, "sym": sym, "dir": d, "status": t["status"],
        "net": float(t.get("pnl_net") or 0), "a": a_ok, "b": b_ok, "c_ok": c_ok,
        "c_win": c_win, "d": True, "trig_ext": _trig_ext(df, trig_s, long),
        "why": b_why[:110],
        "created": str(t.get("pending_created_at") or t.get("entry_time") or "")[:19],
        "htf": htf, "trig": trig_s,
    })

# D: в одном окне второй триггер не глубже предыдущего (равенство = невалидно)
groups = defaultdict(list)
for i, r in enumerate(rows):
    groups[(r["sym"], r["dir"], r["htf"])].append(i)
for idxs in groups.values():
    idxs.sort(key=lambda i: rows[i]["created"])
    best = None
    for i in idxs:
        ext = rows[i]["trig_ext"]
        if ext is None:
            continue
        if best is None:
            best = ext
            continue
        if B._is_resweep_extreme(rows[i]["dir"], ext, best):
            best = ext
        else:
            rows[i]["d"] = False
            rows[i]["why"] = (
                (rows[i]["why"] + " | " if rows[i]["why"] else "")
                + f"триггер не обновил предыдущий: {ext:g} vs {best:g}"
            )

for r in rows:
    r["bad"] = (not r["a"]) or (not r["b"]) or (not r["c_win"]) or (not r["d"])

print(f"{'id':10s} {'sym':5s} {'dir':5s} {'status':12s} {'net':>8s} A B C_ok C_win D  verdict")
for r in rows:
    print(f"{r['id']:10s} {r['sym']:5s} {r['dir']:5s} {r['status']:12s} {r['net']:+8.4f} "
          f"{'y' if r['a'] else 'N'} {'y' if r['b'] else 'N'} {str(r['c_ok'])[0]}  {str(r['c_win'])[0]}  "
          f"{'y' if r['d'] else 'N'}   "
          f"{'УДАЛИТЬ' if r['bad'] else 'оставить'}   {r['why']}")

rm = [r for r in rows if r["bad"]]
keep = [r for r in rows if not r["bad"]]
print()
print(f"всего сделок в statе: {len(rows)} | удалить: {len(rm)} | оставить: {len(keep)}")
print(f"удаляемые: {[(r['sym'], r['net'], r['id']) for r in rm]}")
print(f"сумма удаляемых: {sum(r['net'] for r in rm):+.4f} | сумма оставшихся: {sum(r['net'] for r in keep):+.4f}")
print(f"баланс сейчас: 100 {sum(r['net'] for r in rows):+.4f} = {100 + sum(r['net'] for r in rows):.4f}")
print(f"баланс после чистки: {100 + sum(r['net'] for r in keep):.4f}")

if APPLY:
    ids = {r["id"] for r in rm}
    shutil.copy(BASE / "shadow_trades.json", BASE / "shadow_trades.json.bak_pre_cleanup")
    shutil.copy(BASE / "shadow_positions.json", BASE / "shadow_positions.json.bak_pre_cleanup")
    new_trades = [t for t in trades if t["id"] not in ids]
    (BASE / "shadow_trades.json").write_text(
        json.dumps(new_trades, indent=2, ensure_ascii=False), encoding="utf-8")
    n_marked = 0
    for p in pos_list:
        if p["id"] in ids:
            p["status"] = "voided_invalid_setup"
            p["void_reason"] = "не прошёл новые гейты (см. cleanup_stats.py)"
            p["void_at"] = "2026-09-16T19:30:00"
            n_marked += 1
    (BASE / "shadow_positions.json").write_text(
        json.dumps(pos_list, indent=2, ensure_ascii=False), encoding="utf-8")
    note = {"event": "stats_cleanup", "mode": "shadow",
            "removed_ids": sorted(ids), "kept": len(new_trades),
            "balance_after": round(100 + sum(r["net"] for r in keep), 4),
            "logged_at": dt.datetime.now(TZ).isoformat()}
    with open(BASE / "trade_logs" / "trades_2026-09.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(note, ensure_ascii=False) + "\n")
    print(f"\nAPPLIED: trades {len(trades)} -> {len(new_trades)}, positions помечено: {n_marked}")

"""Сколько tf8-сигналов прошли бы правило «CISD подтверждается закрытием 30m-свечи за уровнем».

Правило пользователя: подтверждённый сетап = 30m-свеча закрылась за уровнем старт-бара (cisd_level);
для LONG close > cisd_level (и close > open, как в find_confirmation), для SHORT зеркально.

Сверяем с журналом бота: у каждой лимитки tf8 смотрим, было ли 30m-закрытие за уровнем
(а) до момента создания лимитки, (б) до закрытия 30m-бара, содержащего момент создания.
"""
import glob
import json
import datetime as dt
from pathlib import Path

import ccxt

BASE = Path("/opt/cisdbotbybit")
ex = ccxt.bybit({"enableRateLimit": True})
UTC = dt.timezone.utc

rows = []
for f in sorted(glob.glob(str(BASE / "trade_logs" / "trades_*.jsonl"))):
    for line in open(f, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get("event") == "pending_created" and r.get("tf") == "tf8":
            rows.append(r)

print("tf8-лимиток в журнале:", len(rows))


def ms(s):
    d = dt.datetime.fromisoformat(str(s))
    return int((d.replace(tzinfo=UTC) if d.tzinfo is None else d).timestamp() * 1000)


def floor30(ts_ms):
    return (ts_ms // (30 * 60 * 1000)) * (30 * 60 * 1000)


res = []
for r in rows:
    sym = f"{r.get('symbol')}/USDT:USDT"
    d = r.get("direction")
    lvl = float(r.get("cisd_level") or r.get("signal_entry") or 0)
    t_created = ms(r["pending_created_at"])
    trig = r.get("trigger_bar_at") or r.get("pending_created_at")
    t_trig = floor30(ms(trig))
    t_end = floor30(t_created) + 30 * 60 * 1000          # закрытие 30m-бара, содержащего создание
    try:
        o = ex.fetch_ohlcv(sym, "30m", since=t_trig, limit=30)
    except Exception as e:
        print("FETCH_ERR", sym, e)
        continue
    bars = [k for k in o if t_trig <= k[0] <= t_end]
    conf_before = conf_by_close = None
    for k in bars:
        o_, h, l, c = k[1], k[2], k[3], k[4]
        beyond = (c > lvl and c > o_) if d == "LONG" else (c < lvl and c < o_)
        if not beyond:
            continue
        close_ts = k[0] + 30 * 60 * 1000
        if close_ts <= t_created and conf_before is None:
            conf_before = dt.datetime.fromtimestamp(k[0] / 1000, UTC).strftime("%m-%d %H:%M")
        if close_ts <= t_end and conf_by_close is None:
            conf_by_close = dt.datetime.fromtimestamp(k[0] / 1000, UTC).strftime("%m-%d %H:%M")
    res.append((r["pending_created_at"][:16], r.get("symbol"), d, lvl, conf_before, conf_by_close,
                r.get("status")))

print()
print(f"{'created(UTC)':16s} {'sym':5s} {'dir':5s} {'level':>10s} 30m-confirm до создания | до закрытия бара создания | status")
n_no = 0
for x in res:
    if not x[5]:
        n_no += 1
    print(f"{x[0]:16s} {x[1]:5s} {x[2]:5s} {x[3]:>10} {str(x[4]):>24s} | {str(x[5]):>24s} | {x[6]}")
print()
print("итого tf8-лимиток:", len(res))
print("без 30m-подтверждения к моменту создания:", sum(1 for x in res if not x[4]))
print("без 30m-подтверждения даже к закрытию бара создания:", n_no)

"""Какое ФАКТИЧЕСКОЕ окно жизни лимитки даёт движок vs live-номинал?

live: created + limit_h (tf7 20м, tf8 30м).
бэк: [fill_from_ts, expire_ts], expire = конец бара (created_bar + limit_bars).
"""
import pickle
import sys

import pandas as pd

sys.path.insert(0, r"D:/PYTHON")
sys.path.insert(0, r"D:/PYTHON/CISDBOT")

from backtest.data import load_ltf

cfg = {
    "tf7": {"main": "5m", "lb": 4, "live_min": 20},
    "tf8": {"main": "30m", "lb": 1, "live_min": 30},
}

for prof, c in cfg.items():
    f = rf"D:/PYTHON/CISDBOT/RUNS/2026-09-12/bot_aligned/SOL_{prof}_2024-01-01_2024-12-31.pkl"
    ck = pickle.load(open(f, "rb"))
    sigs = {str(s.get("hash")): s for s in ck.get("signals") or []}
    trades = [t for t in ck.get("trades") or [] if t.get("entry_kind") == "LIMIT"]
    df, _ = load_ltf(tf=c["main"], since="2024-01-01", until="2024-12-31", symbol="SOL")
    df.index = pd.DatetimeIndex(df.index)
    m = c["main"]
    lb = c["lb"]

    d_created, d_cbt, d_fill, d_left = [], [], [], []
    for t in trades:
        s = sigs.get(str(t.get("hash")))
        if not s:
            continue
        cb = int(t["created_bar"]); eb = int(t["entry_bar"])
        exp_i = min(cb + lb, len(df) - 1)
        t_created = pd.Timestamp(df.index[cb])
        t_expire = pd.Timestamp(df.index[exp_i]) + pd.Timedelta(minutes=int(m[:-1]))
        t_fill = pd.Timestamp(df.index[eb])
        cbt = pd.Timestamp(str(s.get("confirm_bar_time")))
        d_created.append((t_expire - t_created).total_seconds() / 60)
        d_cbt.append((t_expire - cbt).total_seconds() / 60)
        d_fill.append((t_fill - t_created).total_seconds() / 60)
        d_left.append((t_expire - t_fill).total_seconds() / 60)

    for name, arr in (("created→expire", d_created), ("cbt→expire", d_cbt),
                      ("created→fill", d_fill), ("fill→expire", d_left)):
        s = pd.Series(arr)
        print(f"{prof} {name:14}: медиана {s.median():5.1f}м | p10 {s.quantile(0.1):5.1f} | p90 {s.quantile(0.9):5.1f} | мин {s.min():5.1f} | макс {s.max():5.1f}")
    print(f"{prof} LIVE номинал (created+{c['live_min']}м). сделок: {len(d_created)}")
    print()

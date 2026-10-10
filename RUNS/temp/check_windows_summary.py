"""Сводка окон отмены: бэк vs live. SOL/ETH, 2024/2025."""
import pickle
import sys

import pandas as pd

sys.path.insert(0, r"D:/PYTHON")
sys.path.insert(0, r"D:/PYTHON/CISDBOT")

from backtest.data import load_ltf

cfg = {
    "tf7": {"main": "5m", "lb": 4, "conf_min": 1, "live_min": 20},
    "tf8": {"main": "30m", "lb": 1, "conf_min": 5, "live_min": 30},
}

for sym in ("SOL", "ETH"):
    for year in ("2024", "2025"):
        for prof, c in cfg.items():
            f = rf"D:/PYTHON/CISDBOT/RUNS/2026-09-12/bot_aligned/{sym}_{prof}_{year}-01-01_{year}-12-31.pkl"
            try:
                ck = pickle.load(open(f, "rb"))
            except Exception:
                # fallback: 09-11 папка
                f = rf"D:/PYTHON/CISDBOT/RUNS/2026-09-11/bot_aligned/{sym}_{prof}_{year}-01-01_{year}-12-31.pkl"
                try:
                    ck = pickle.load(open(f, "rb"))
                except Exception as e:
                    print(f"{sym} {prof} {year}: нет кэша ({e})")
                    continue
            sigs = {str(s.get("hash")): s for s in ck.get("signals") or []}
            trades = [t for t in ck.get("trades") or [] if t.get("entry_kind") == "LIMIT"]
            df, _ = load_ltf(tf=c["main"], since=f"{year}-01-01", until=f"{year}-12-31", symbol=sym)
            df.index = pd.DatetimeIndex(df.index)
            lb, m = c["lb"], c["main"]
            d_win, d_wait = [], []
            for t in trades:
                s = sigs.get(str(t.get("hash")))
                if not s:
                    continue
                cb = int(t["created_bar"])
                exp_i = min(cb + lb, len(df) - 1)
                t_expire = pd.Timestamp(df.index[exp_i]) + pd.Timedelta(minutes=int(m[:-1]))
                cbt = pd.Timestamp(str(s.get("confirm_bar_time")))
                fill_from = (cbt + pd.Timedelta(minutes=c["conf_min"])).ceil("5min")
                d_win.append((t_expire - fill_from).total_seconds() / 60)
                d_wait.append((cbt + pd.Timedelta(minutes=c["conf_min"]) and (t_expire - cbt).total_seconds() / 60))
            s_win = pd.Series(d_win)
            print(f"{sym} {prof} {year}: окно[постановка→отмена] медиана {s_win.median():5.0f}м "
                  f"(p10 {s_win.quantile(.1):4.0f} / p90 {s_win.quantile(.9):4.0f}) | live: {c['live_min']}м | n={len(d_win)}")

"""Сверка: видит ли честный движок бэктеста реальные сделки бота (tf8, 16–21.09.2026).

Кэши бэктеста кончаются 2026-09-06, поэтому свечи на период живых сделок
догружены с Bybit (`fetch_bybit_5m.py`) — то есть сверка идёт на том же
источнике цен, на котором работал бот.

Матчим сигнал бэктеста с живой сделкой по паре + уровню CISD (он же цена входа)
с допуском 0,05% и по времени постановки лимитки ±2 часа. Хэши не сравниваем:
живой бот и бэктест — разные репозитории, функция хэша может не совпадать.

Запуск: python recon_live_bt.py
"""
from __future__ import annotations

import logging
import os
import pickle
import sys

import pandas as pd

sys.path.insert(0, r"D:/PYTHON/CISDBOT")
logging.disable(logging.INFO)

DATA = "D:/PYTHON/cisdbotbybit/RUNS/temp/data_live_sep2026"
LIVE = "D:/PYTHON/cisdbotbybit/RUNS/live_trades_tf8/LIVE_TRADES_tf8_30m-8H.csv"
CACHE = "D:/PYTHON/cisdbotbybit/RUNS/temp/recon_live_bt.pkl"
PAIRS = ["BTC", "ETH", "DOGE", "KAS", "ADA", "BNB", "LINK", "LTC", "XRP", "SOL"]
SINCE, UNTIL = "2026-08-25", "2026-09-22"
LVL_TOL = 0.0005          # 0,05% по уровню входа
T_TOL = pd.Timedelta(hours=2)


def run_bt() -> dict:
    if os.path.exists(CACHE):
        return pickle.load(open(CACHE, "rb"))
    from backtest.bot_aligned import run_bot_aligned_backtest
    out = {}
    for sym in PAIRS:
        csv = f"{DATA}/{sym}USDT_5m_bybit.csv"
        try:
            res = run_bot_aligned_backtest(
                since=SINCE, until=UNTIL, profile="tf8", symbol=sym, csv=csv,
                limit_bars=1, pos_bars=12, save=False, quiet=True,
                detect_filters={"atr_enabled": False, "vol_enabled": False, "d_enabled": False},
                mss_on_ltf=False,
            )
            out[sym] = {"signals": res.get("signals") or [], "trades": res.get("trades") or []}
            print(f"{sym}: сигналов {len(out[sym]['signals'])}, "
                  f"сделок {len(out[sym]['trades'])}", flush=True)
        except Exception as e:
            out[sym] = {"signals": [], "trades": [], "error": repr(e)}
            print(f"{sym}: FAIL {e!r}", flush=True)
    pickle.dump(out, open(CACHE, "wb"))
    return out


def main() -> None:
    live = pd.read_csv(LIVE)
    live["pending_created_at"] = pd.to_datetime(live["pending_created_at"])
    bt = run_bt()

    print(f"\nживых сделок {len(live)} (включая открытые)")
    print("сигналов бэктеста по парам:",
          {s: len(bt[s]["signals"]) for s in PAIRS})

    rows = []
    for _, t in live.iterrows():
        sym = t["symbol_key"]
        lvl = float(t["cisd_level"])
        t0 = t["pending_created_at"]
        best = None
        for s in bt.get(sym, {}).get("signals", []):
            if str(s.get("direction")) != t["direction"]:
                continue
            e = float(s.get("entry") or 0)
            if e <= 0 or abs(e - lvl) / lvl > LVL_TOL:
                continue
            cbt = pd.Timestamp(str(s.get("confirm_bar_time")))
            anchor = (cbt + pd.Timedelta(minutes=30)).ceil("5min")
            if abs(anchor - t0) > T_TOL:
                continue
            d = abs(anchor - t0)
            if best is None or d < best[0]:
                best = (d, s, anchor)
        # была ли по этому сигналу сделка в бэктесте
        got_trade = None
        if best is not None:
            hs = str(best[1].get("hash"))
            for tr in bt[sym]["trades"]:
                if str(tr.get("signal_hash") or tr.get("hash")) == hs:
                    got_trade = tr
                    break
        rows.append({
            "id": t["id"], "sym": sym, "dir": t["direction"], "status": t["status"],
            "live_anchor": t0, "matched": best is not None,
            "bt_anchor": best[2] if best else None,
            "dt_min": round((best[2] - t0).total_seconds() / 60, 1) if best else None,
            "bt_filled": got_trade is not None,
        })
    r = pd.DataFrame(rows)
    print(f"\nнайдено в сигналах бэктеста: {int(r.matched.sum())} из {len(r)}")
    print(f"дошло до сделки в бэктесте:   {int(r.bt_filled.sum())} из {len(r)}")
    print("\nпо статусу живой сделки:")
    print(r.groupby("status")[["matched", "bt_filled"]].agg(["sum", "count"]).to_string())
    print("\nнесовпавшие:")
    print(r[~r.matched][["id", "sym", "dir", "status", "live_anchor"]].to_string(index=False))
    print("\nсовпавшие, но не заполненные в бэктесте:")
    print(r[r.matched & ~r.bt_filled][["id", "sym", "dir", "status", "dt_min"]].to_string(index=False))
    r.to_csv("D:/PYTHON/cisdbotbybit/RUNS/temp/recon_live_bt.csv", index=False)


if __name__ == "__main__":
    main()

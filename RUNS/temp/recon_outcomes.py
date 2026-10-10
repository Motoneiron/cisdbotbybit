"""Сверка исходов сделка-в-сделку: бэктест с тейком 1R против живого бота.

Прямой прогон движка сравнивать по исходам нельзя: для tf8 он ставит тейк по фибо
(в окне вышло в среднем 2,3R), а живой бот — ровно 1R (`_tp_1r`). Поэтому исходы
пересчитываем сами по тем же 5m свечам Bybit: от якоря филла вперёд 6 часов,
что случится раньше — TP на 1R, стоп или таймаут.

Сопоставление живой сделки и сигнала бэктеста — как в recon_live_bt.py
(пара + направление + уровень входа ±0,05% + якорь ±2ч).

Запуск: python recon_outcomes.py
"""
from __future__ import annotations

import pickle

import pandas as pd

BASE = "D:/PYTHON/cisdbotbybit/RUNS/temp"
DATA = f"{BASE}/data_live_sep2026"
LIVE = "D:/PYTHON/cisdbotbybit/RUNS/live_trades_tf8/LIVE_TRADES_tf8_30m-8H.csv"
LVL_TOL, T_TOL = 0.0005, pd.Timedelta(hours=2)
HOLD = pd.Timedelta(hours=6)
LIMIT_LIFE = pd.Timedelta(minutes=30)


def bars(sym: str) -> pd.DataFrame:
    d = pd.read_csv(f"{DATA}/{sym}USDT_5m_bybit.csv", parse_dates=["timestamp"])
    return d.set_index("timestamp")


def sim(b: pd.DataFrame, anchor: pd.Timestamp, direction: str,
        entry: float, stop: float) -> tuple[str, float, pd.Timestamp | None]:
    """Лимитка живёт 30 мин, затем 6ч удержания с тейком 1R."""
    long = direction == "LONG"
    risk = abs(entry - stop)
    tp = entry + risk if long else entry - risk
    win = b[(b.index >= anchor) & (b.index < anchor + LIMIT_LIFE)]
    fill = None
    for ts, row in win.iterrows():
        if (long and row.low <= entry) or (not long and row.high >= entry):
            fill = ts
            break
    if fill is None:
        return "no_fill", 0.0, None
    pos = b[(b.index >= fill) & (b.index <= fill + HOLD)]
    for ts, row in pos.iterrows():
        hit_tp = row.high >= tp if long else row.low <= tp
        hit_sl = row.low <= stop if long else row.high >= stop
        if hit_tp and hit_sl:
            return "ambig", 0.0, ts          # внутри 5m бара порядок неизвестен
        if hit_tp:
            return "tp", 1.0, ts
        if hit_sl:
            return "sl", -1.0, ts
    px = float(pos.close.iloc[-1]) if len(pos) else entry
    r = (px - entry) / risk if long else (entry - px) / risk
    return "time", r, pos.index[-1] if len(pos) else None


def main() -> None:
    bt = pickle.load(open(f"{BASE}/recon_live_bt.pkl", "rb"))
    live = pd.read_csv(LIVE)
    live["pending_created_at"] = pd.to_datetime(live["pending_created_at"])
    live = live[live.status != "open"]
    cache = {s: bars(s) for s in bt}

    rows = []
    for _, t in live.iterrows():
        sym, lvl, t0 = t["symbol_key"], float(t["cisd_level"]), t["pending_created_at"]
        best = None
        for s in bt.get(sym, {}).get("signals", []):
            if str(s.get("direction")) != t["direction"]:
                continue
            e = float(s.get("entry") or 0)
            if e <= 0 or abs(e - lvl) / lvl > LVL_TOL:
                continue
            a = (pd.Timestamp(str(s.get("confirm_bar_time")))
                 + pd.Timedelta(minutes=30)).ceil("5min")
            if abs(a - t0) > T_TOL:
                continue
            if best is None or abs(a - t0) < abs(best[0] - t0):
                best = (a, s)
        if best is None:
            rows.append({"id": t["id"], "sym": sym, "live": t["status"][7:], "bt": "нет сигнала"})
            continue
        a, s = best
        out, r, when = sim(cache[sym], a, t["direction"],
                           float(s.get("entry")), float(s.get("stop")))
        rows.append({
            "id": t["id"], "sym": sym, "dir": t["direction"],
            "live": t["status"].replace("closed_", ""), "bt": out, "bt_r": round(r, 2),
            "anchor_dt_min": round((a - t0).total_seconds() / 60, 1),
        })
    r = pd.DataFrame(rows)
    print(r.to_string(index=False))
    m = r[r.bt.isin(["tp", "sl", "time"])]
    print(f"\nсравнимых пар: {len(m)} из {len(r)}")
    print("\nматрица исходов (строки — живой бот, столбцы — бэктест с тейком 1R):")
    print(pd.crosstab(m.live, m.bt).to_string())
    same = int((m.live == m.bt).sum())
    print(f"\nсовпало исходов: {same} из {len(m)} ({same/len(m)*100:.0f}%)")
    print("\nсводка:")
    print(f"  живой бот:  " + ", ".join(f"{k} {v}" for k, v in m.live.value_counts().items()))
    print(f"  бэктест 1R: " + ", ".join(f"{k} {v}" for k, v in m.bt.value_counts().items()))


if __name__ == "__main__":
    main()

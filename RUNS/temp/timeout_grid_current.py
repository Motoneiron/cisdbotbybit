"""ПЕРЕПРОВЕРКА окна ожидания лимитки (tf8) на ТЕКУЩЕМ конфиге бота.

Отличия от прошлой честной сетки (honest_timeout_grid.py, 13.09):
  - окно стартует от ЗАКРЫТИЯ 30m-конфирм-бара (confirm 30m, а не 5m): from_ts = ceil5(cbt + 30мин);
  - фильтры бота сейчас: min_stop 0.5%, vwap-гейт ВЫКЛЮЧЕН;
  - выход = TP1R (как живой), позиция 6ч, комиссии Bybit (maker 0.036 / taker 0.10);
  - tf8-only, 10 пар, полная история (до мая 2026 — дальше датасета нет).

Метод: numpy по 1m-сегментам (searchsorted), без iterrows.
"""
import glob
import pickle
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, r"D:/PYTHON")
sys.path.insert(0, r"D:/PYTHON/CISDBOT")
from backtest.data import load_ltf  # noqa: E402

MAKER, TAKER = 0.00036, 0.0010
MIN_STOP = float(__import__("os").environ.get("MIN_STOP", "0.005"))  # порог стопа
CONF_MIN = int(__import__("os").environ.get("CONF_MIN", "30"))  # якорь: закрытие конфирм-бара
POS_H = 6
XS = [15, 20, 30, 45, 60, 90, 120, 180]
PAIRS = ["BTC", "ETH", "DOGE", "KAS", "ADA", "BNB", "LINK", "LTC", "XRP", "SOL"]


def run_pair(sym):
    rows = []
    for f in sorted(glob.glob(f"D:/PYTHON/CISDBOT/RUNS/filters_off_full/{sym}_tf8_*.pkl")):
        c = pickle.load(open(f, "rb"))
        sigs = {str(s.get("hash")): s for s in c.get("signals") or []}
        trades = [t for t in c.get("trades") or [] if t.get("entry_kind") == "LIMIT"]
        if not trades:
            continue
        year = int(str(c.get("since"))[:4])
        try:
            df1, _ = load_ltf(tf="1m", since=f"{year}-01-01", until=f"{year}-12-31", symbol=sym)
        except Exception as e:
            print(f"  {sym} {year}: нет 1m данных ({e!r})", flush=True)
            continue
        ts = pd.DatetimeIndex(df1.index).to_numpy(dtype="datetime64[ns]").astype("int64") // 60_000_000_000
        hi = df1["high"].to_numpy(dtype=float)
        lo = df1["low"].to_numpy(dtype=float)
        cl = df1["close"].to_numpy(dtype=float)
        step_min = int(round(np.median(np.diff(ts)))) if len(ts) > 2 else 1
        step_min = max(1, step_min)

        for t in trades:
            s = sigs.get(str(t.get("hash")))
            if not s:
                continue
            entry, stop = float(t.get("entry_px") or 0), float(t.get("stop") or 0)
            if entry <= 0 or stop <= 0:
                continue
            sp = abs(entry - stop) / entry
            if sp < MIN_STOP:
                continue
            long = t.get("direction") == "LONG"
            cbt = pd.Timestamp(str(s.get("confirm_bar_time")))
            from_ts = (cbt + pd.Timedelta(minutes=CONF_MIN)).ceil("5min")
            t0 = int(from_ts.value // 60_000_000_000)
            i0 = int(np.searchsorted(ts, t0, side="left"))
            if i0 >= len(ts):
                continue
            max_bars = int(XS[-1] / step_min)
            sl = slice(i0, min(len(ts), i0 + max_bars + 1))
            seg_lo, seg_hi = lo[sl], hi[sl]
            hit = np.where(seg_lo <= entry)[0] if long else np.where(seg_hi >= entry)[0]
            if len(hit) == 0:
                continue
            j = i0 + int(hit[0])
            dt_min = float(ts[j] - t0)
            # исход от касания: TP1R / SL / TIME(6ч)
            tp1 = entry + (entry - stop) if long else entry - (stop - entry)
            ks = slice(j, min(len(ts), j + int(POS_H * 60 / step_min) + 1))
            kl, kh = lo[ks], hi[ks]
            tp_hit = np.where(kh >= tp1)[0] if long else np.where(kl <= tp1)[0]
            sl_hit = np.where(kl <= stop)[0] if long else np.where(kh >= stop)[0]
            i_tp = int(tp_hit[0]) if len(tp_hit) else 10 ** 9
            i_sl = int(sl_hit[0]) if len(sl_hit) else 10 ** 9
            if i_tp <= i_sl and i_tp != 10 ** 9:
                out, r = "tp", 1.0 - 2 * MAKER / sp
            elif i_sl != 10 ** 9:
                out, r = "sl", -1.0 - MAKER / sp - TAKER / sp
            else:
                px = float(cl[ks][-1])
                out = "time"
                r = ((px - entry) / (entry - stop) if long else (entry - px) / (stop - entry)) - MAKER / sp - TAKER / sp
            for x in XS:
                if dt_min <= x:
                    rows.append({"sym": sym, "year": year, "x": x, "out": out, "r": r, "dir": t.get("direction")})
    return rows


if __name__ == "__main__":
    only = sys.argv[1].split(",") if len(sys.argv) > 1 else PAIRS
    all_rows = []
    for sym in only:
        try:
            r = run_pair(sym)
            all_rows += r
            n30 = sum(1 for z in r if z["x"] == 30)
            print(f"{sym}: кандидатов(30м)={n30} готово", flush=True)
        except Exception as e:
            print(f"{sym}: FAILED {e!r}", flush=True)
    df = pd.DataFrame(all_rows)
    df.to_pickle("D:/PYTHON/cisdbotbybit/RUNS/temp/timeout_grid_current.pkl")
    print()
    print("=== СЕТКА ОКНА ЛИМИТКИ (tf8, TP1R, min_stop 0.5%, vwap off, confirm 30m) ===")
    print(f"{'окно':>6} | {'сделок':>6} | {'TP':>5} {'SL':>5} {'TIME':>5} | {'WR':>6} | {'ΣR':>8} | {'avg':>6} | добавка к пред.")
    prev = None
    for x in XS:
        d = df[df.x == x]
        if d.empty:
            continue
        tp = int((d.out == "tp").sum()); sl = int((d.out == "sl").sum()); tm = int((d.out == "time").sum())
        wr = 100 * tp / max(1, tp + sl)
        add = "" if prev is None else f"n {len(d) - prev[0]:+5d} / ΣR {d.r.sum() - prev[1]:+7.1f}"
        print(f"{x:5d}м | {len(d):6d} | {tp:5d} {sl:5d} {tm:5d} | {wr:5.1f}% | {d.r.sum():+8.1f} | {d.r.mean():+.3f} | {add}")
        prev = (len(d), d.r.sum())
    print()
    d30 = df[df.x == 30]
    best = max(XS, key=lambda x: df[df.x == x].r.sum() if len(df[df.x == x]) else -1e9)
    print(f"текущее окно бота 30м: ΣR {d30.r.sum():+.1f} | пик сетки: {best}м ΣR {df[df.x == best].r.sum():+.1f} "
          f"(разница {df[df.x == best].r.sum() - d30.r.sum():+.1f}R)")

"""НОЧЬ, шаг 1 — честная по-сделочная база tf8.

Для каждого сетапа из кэшей filters_off_full_aligned/<PAIR>_tf8_<year>.pkl:
  * ФИЧИ (причинно, только закрытые бары) на двух якорях постановки лимитки:
      anchor=5  — канон (cbt+5), содержит look-ahead относительно 30m-закрытия
      anchor=30 — исполнимый (вход после закрытия 30m-бара)
    фичи: vd (дневной VWAP, ATR14 на 30m), slope EMA3 по 1h / 4h / 1d,
          расстояние до дневного open (в ATR).
  * ИСХОДЫ: TP1R / SL / TIME(6ч) по 1m, комиссии Bybit, окно поиска входа 15/20/30/45/60 мин.

Результат: по одному pkl на пару-год в RUNS/temp/night_core/ (безопасно для長 прогона).
"""
import glob
import os
import pickle
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, r"D:/PYTHON")
sys.path.insert(0, r"D:/PYTHON/CISDBOT")
from backtest.data import load_ltf                       # noqa: E402
from backtest.sweep_atr_filter import compute_atr14      # noqa: E402
from backtest.vwap_filter import daily_session_vwap      # noqa: E402

MAKER, TAKER = 0.00036, 0.0010
MIN_STOP, POS_H = 0.0025, 6
WINDOWS = [15, 20, 30, 45, 60]
ANCHORS = [5, 30]
PAIRS = ["BTC", "ETH", "DOGE", "KAS", "ADA", "BNB", "LINK", "LTC", "XRP", "SOL"]
OUTDIR = "D:/PYTHON/cisdbotbybit/RUNS/temp/night_core_aligned"
os.makedirs(OUTDIR, exist_ok=True)


def slope_series(close: pd.Series, span: int = 3) -> pd.Series:
    e = close.ewm(span=span, adjust=False).mean()
    return ((e / e.shift(1) - 1) * 100).dropna()


def lookup(ser: pd.Series, close_times: pd.DatetimeIndex, anchor: pd.Timestamp):
    """Значение серии по последнему бару, у которого close_time <= anchor."""
    k = int(close_times.searchsorted(anchor, side="right")) - 1
    if k < 0:
        return None
    return float(ser.iloc[k]) if np.isfinite(ser.iloc[k]) else None


for sym in PAIRS:
    for f in sorted(glob.glob(f"D:/PYTHON/CISDBOT/RUNS/filters_off_full_aligned/{sym}_tf8_*.pkl")):
        year = int(str(os.path.basename(f)).split("_")[-1][:4])
        outfile = f"{OUTDIR}/{sym}_{year}.pkl"
        if os.path.exists(outfile):
            print(f"  skip {sym} {year}", flush=True)
            continue
        c = pickle.load(open(f, "rb"))
        sigs = {str(s.get("hash")): s for s in c.get("signals") or []}
        trades = [t for t in c.get("trades") or [] if t.get("entry_kind") == "LIMIT"]
        if not trades:
            continue
        try:
            df1, _ = load_ltf(tf="1m", since=f"{year}-01-01", until=f"{year}-12-31", symbol=sym)
            d30, _ = load_ltf(tf="30m", since=f"{year}-01-01", until=f"{year}-12-31", symbol=sym)
        except Exception as e:
            print(f"  DATA FAIL {sym} {year}: {e!r}", flush=True)
            continue
        idx30 = pd.DatetimeIndex(d30.index)
        ct30 = idx30 + pd.Timedelta(minutes=30)
        vwap30 = daily_session_vwap(d30)
        atr30 = compute_atr14(d30)
        op30 = d30["open"].to_numpy(dtype=float)
        # дневной open: разворот по дате
        day_key = idx30.normalize()
        day_open_map: dict = {}
        for i, dk in enumerate(day_key):
            day_open_map.setdefault(dk, float(op30[i]))
        series = {}
        for lbl, rule in (("s1h", "1h"), ("s4h", "4h"), ("s1d", "1d")):
            ser = slope_series(d30["close"].resample(rule, label="left", closed="left").last().dropna())
            series[lbl] = (ser, pd.DatetimeIndex(ser.index) + pd.Timedelta(rule))
        ts = pd.DatetimeIndex(df1.index).to_numpy(dtype="datetime64[ns]").astype("int64") // 60_000_000_000
        hi, lo, cl = (df1[k].to_numpy(dtype=float) for k in ("high", "low", "close"))
        step = max(1, int(round(np.median(np.diff(ts)))))
        rows = []
        for t in trades:
            s = sigs.get(str(t.get("hash")))
            if not s:
                continue
            entry, stop = float(t.get("entry_px") or 0), float(t.get("stop") or 0)
            if entry <= 0 or stop <= 0:
                continue
            sp_ = abs(entry - stop) / entry
            if sp_ < MIN_STOP:
                continue
            long = t.get("direction") == "LONG"
            cbt = pd.Timestamp(str(s.get("confirm_bar_time")))
            base = {"sym": sym, "year": year, "dir": t.get("direction"), "cbt": cbt,
                    "entry": entry, "stop": stop, "stop_pct": sp_ * 100,
                    "htf_time": str(s.get("htf_time") or ""), "hash": str(t.get("hash"))}
            for anchor_min in ANCHORS:
                anchor_ts = cbt + pd.Timedelta(minutes=anchor_min)
                j30 = int(ct30.searchsorted(anchor_ts, side="right")) - 1
                feats = {}
                if j30 >= 14:
                    at = float(atr30.iloc[j30]); vw = float(vwap30.iloc[j30])
                    cl30 = float(d30["close"].iloc[j30])
                    dk = idx30[j30].normalize()
                    do = day_open_map.get(dk)
                    feats["atr30"] = at
                    feats["vd"] = (cl30 - vw) / at if at > 0 and np.isfinite(vw) else None
                    feats["dopen_atr"] = (cl30 - do) / at if (do and at > 0) else None
                for lbl in ("s1h", "s4h", "s1d"):
                    ser, ct = series[lbl]
                    feats[lbl] = lookup(ser, ct, anchor_ts)
                for W in WINDOWS:
                    from_ts = anchor_ts.ceil("5min")
                    t0 = int(from_ts.value // 60_000_000_000)
                    i0 = int(np.searchsorted(ts, t0, side="left"))
                    if i0 >= len(ts):
                        continue
                    seg = slice(i0, min(len(ts), i0 + int(W / step) + 1))
                    hit = np.where(lo[seg] <= entry)[0] if long else np.where(hi[seg] >= entry)[0]
                    if len(hit) == 0:
                        out, r, filled = "nofill", 0.0, False
                        rows.append({**base, **feats, "anchor": anchor_min, "win": W,
                                     "out": out, "r": r, "filled": filled})
                        continue
                    j = i0 + int(hit[0])
                    tp1 = entry + (entry - stop) if long else entry - (stop - entry)
                    ks = slice(j, min(len(ts), j + int(POS_H * 60 / step) + 1))
                    kl, kh = lo[ks], hi[ks]
                    tp_hit = np.where(kh >= tp1)[0] if long else np.where(kl <= tp1)[0]
                    sl_hit = np.where(kl <= stop)[0] if long else np.where(kh >= stop)[0]
                    i_tp = int(tp_hit[0]) if len(tp_hit) else 10 ** 9
                    i_sl = int(sl_hit[0]) if len(sl_hit) else 10 ** 9
                    if i_tp <= i_sl and i_tp != 10 ** 9:
                        out, r, ix = "tp", 1.0 - 2 * MAKER / sp_, i_tp
                    elif i_sl != 10 ** 9:
                        out, r, ix = "sl", -1.0 - (MAKER + TAKER) / sp_, i_sl
                    else:
                        px = float(cl[ks][-1])
                        out = "time"
                        ix = int(cl[ks].size) - 1
                        r = ((px - entry) / (entry - stop) if long else (entry - px) / (stop - entry)) - (MAKER + TAKER) / sp_
                    xe = min(j + ix, len(ts) - 1)
                    rows.append({**base, **feats, "anchor": anchor_min, "win": W,
                                 "out": out, "r": r, "filled": True,
                                 "fill_min": float(ts[j] - t0), "exit_min": float(ts[xe] - ts[j])})
        pickle.dump(rows, open(outfile, "wb"))
        print(f"  {sym} {year}: {len(rows)} строк ({len(trades)} сетапов)", flush=True)

print("core done", flush=True)

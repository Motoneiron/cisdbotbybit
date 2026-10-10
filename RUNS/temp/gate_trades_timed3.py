"""Пересимуляция + pre-TP: касалась ли цена TP-уровня ДО заполнения лимитки.

Для каждой взятой сделки: pre_tp = (в окне [постановка, заполнение) цена коснулась entry+1R).
Плюс сохраняем entry/stop/tp1. Результат: gate_trades_timed3.pkl.
"""
import glob
import pickle
import re
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, r"D:/PYTHON")
sys.path.insert(0, r"D:/PYTHON/CISDBOT")

from backtest.data import load_ltf
from backtest.sweep_atr_filter import compute_atr14
from cryptofish.adapters.features import daily_session_vwap

MAKER = 0.00036
TAKER = 0.0010
MIN_STOP = 0.0025
NS_MIN = 60_000_000_000


def vd_at(df, i, vwap, atr):
    if i < 0 or i >= len(df):
        return None
    if pd.isna(atr.iloc[i]) or atr.iloc[i] <= 0:
        return None
    return (float(df.iloc[i]["close"]) - float(vwap.iloc[i])) / float(atr.iloc[i])


def main():
    syms = sys.argv[1].split(",") if len(sys.argv) > 1 else \
        ["BTC", "ETH", "DOGE", "KAS", "ADA", "BNB", "LINK", "LTC", "XRP", "SOL"]
    rows = []
    for sym in syms:
        all_files = sorted(glob.glob(rf"D:/PYTHON/CISDBOT/RUNS/*/bot_aligned/{sym}_tf*_*.pkl"),
                           key=lambda p: p.replace("\\", "/"))
        best = {}
        for f in all_files:
            name = f.replace("\\", "/").split("/")[-1]
            m = re.match(rf"{sym}_(tf\d)_(\d{{4}})-\d{{2}}-\d{{2}}_.*\.pkl", name)
            if m:
                best[(m.group(1), m.group(2))] = f
        years = sorted({y for (_, y) in best.keys()})
        for year in years:
            df1 = None
            for prof in ("tf7", "tf8"):
                f = best.get((prof, year))
                if not f:
                    continue
                if prof == "tf8":
                    conf_min, pos_h, W, dft_tf = 5, 6, 30, "30m"
                else:
                    conf_min, pos_h, W, dft_tf = 1, 16, 20, "5m"
                try:
                    c = pickle.load(open(f, "rb"))
                except Exception:
                    continue
                sigs = {str(s.get("hash")): s for s in c.get("signals") or []}
                trades = [t for t in c.get("trades") or [] if t.get("entry_kind") == "LIMIT"]
                if not trades:
                    continue
                dft, _ = load_ltf(tf=dft_tf, since=f"{year}-01-01", until=f"{year}-12-31", symbol=sym)
                dft.index = pd.DatetimeIndex(dft.index)
                atr = compute_atr14(dft)
                vwap = daily_session_vwap(dft)
                if df1 is None:
                    df1, _ = load_ltf(tf="1m", since=f"{year}-01-01", until=f"{year}-12-31", symbol=sym)
                    df1.index = pd.DatetimeIndex(df1.index)
                    t1 = df1.index.to_numpy(dtype="datetime64[ns]").astype("int64") // NS_MIN
                    hi = df1["high"].to_numpy(dtype=float)
                    lo = df1["low"].to_numpy(dtype=float)
                    cl = df1["close"].to_numpy(dtype=float)
                for t in trades:
                    s = sigs.get(str(t.get("hash")))
                    if not s:
                        continue
                    sb = s.get("scan_bar")
                    i = int(sb) if sb is not None and 0 <= int(sb) < len(dft) else None
                    if i is None:
                        continue
                    vd = vd_at(dft, i, vwap, atr)
                    if vd is None:
                        continue
                    entry = float(t["entry_px"]); stop = float(t["stop"])
                    sp = abs(entry - stop) / entry
                    if sp < MIN_STOP:
                        continue
                    direction = t["direction"]
                    long = direction == "LONG"
                    risk = entry - stop if long else stop - entry
                    tp1 = entry + risk if long else entry - risk
                    cbt = pd.Timestamp(str(s.get("confirm_bar_time")))
                    from_ts = (cbt + pd.Timedelta(minutes=conf_min)).ceil("5min")
                    m0 = from_ts.value // NS_MIN
                    i0 = int(np.searchsorted(t1, m0, "left"))
                    iN = int(np.searchsorted(t1, m0 + W, "left"))
                    rec = {"sym": sym, "prof": prof, "year": year, "dir": direction,
                           "vd": float(vd), "sp": sp, "t_ord": int(m0),
                           "htf_time": str(s.get("htf_time") or ""),
                           "entry": entry, "stop": stop,
                           "taken": False, "t_in": None, "t_out": None, "out": "none", "r": 0.0,
                           "pre_tp": False, "pre_tp_at": None}
                    if i0 < iN:
                        seg = lo[i0:iN] <= entry if long else hi[i0:iN] >= entry
                        if seg.any():
                            k = int(np.argmax(seg))
                            hit_i = i0 + k
                            rec["taken"] = True
                            rec["t_in"] = int(t1[hit_i])
                            hit_m = int(t1[hit_i])
                            # pre-TP: касание TP-уровня в окне [постановка, заполнение)
                            if hit_i > i0:
                                pre = hi[i0:hit_i] >= tp1 if long else lo[i0:hit_i] <= tp1
                                if pre.any():
                                    rec["pre_tp"] = True
                                    rec["pre_tp_at"] = int(t1[i0 + int(np.argmax(pre))])
                            j1 = int(np.searchsorted(t1, hit_m + pos_h * 60, "right"))
                            s_lo = lo[hit_i:j1]; s_hi = hi[hit_i:j1]
                            if long:
                                m_sl = s_lo <= stop
                                m_tp = s_hi >= tp1
                            else:
                                m_sl = s_hi >= stop
                                m_tp = s_lo <= tp1
                            i_sl = int(np.argmax(m_sl)) if m_sl.any() else 10**9
                            i_tp = int(np.argmax(m_tp)) if m_tp.any() else 10**9
                            if i_sl <= i_tp and i_sl != 10**9:
                                rec["out"], rec["r"] = "sl", -1.0 - MAKER / sp - TAKER / sp
                                rec["t_out"] = int(t1[min(hit_i + i_sl, len(t1) - 1)])
                            elif i_tp != 10**9:
                                rec["out"], rec["r"] = "tp", 1.0 - 2 * MAKER / sp
                                rec["t_out"] = int(t1[min(hit_i + i_tp, len(t1) - 1)])
                            else:
                                px = float(cl[j1 - 1] if j1 - 1 >= hit_i else cl[hit_i])
                                rec["r"] = ((px - entry) / (entry - stop) if long else (entry - px) / (entry - stop)) \
                                    - MAKER / sp - TAKER / sp
                                rec["out"] = "time"
                                rec["t_out"] = int(t1[j1 - 1])
                            if rec["t_out"] < rec["t_in"]:
                                rec["t_out"] = rec["t_in"]
                    rows.append(rec)
        print(f"{sym}: done ({len(rows)} rows)", flush=True)

    df = pd.DataFrame(rows)
    df.to_pickle(r"D:/PYTHON/cisdbotbybit/RUNS/temp/gate_trades_timed3.pkl")
    tk = df[df.taken]
    print("\n=== БАЗА3 ===", len(df), "| взятых:", len(tk), "| pre_tp:", int(tk.pre_tp.sum()),
          f"({100*tk.pre_tp.mean():.1f}% от взятых)")


if __name__ == "__main__":
    main()

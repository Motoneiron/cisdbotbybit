"""Ре-калибровка VWAP-гейта на ЛАЙВ-якоре конфирма (confirm 5m → from_ts = cbt+5),
честно: vd только по ПОЛНОСТЬЮ закрытым 30m-барам (бар закрыт к from_ts).

Вопрос: держится ли правило бота (LONG vd≥0, SHORT vd≤0) и правило-предшественник (LONG vd≤−3)
на чистом якоре, или оно артефакт scan-бара. Выход TP1R, 6ч, комиссии Bybit, tf8, 10 пар.
"""
import glob
import pickle
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, r"D:/PYTHON")
sys.path.insert(0, r"D:/PYTHON/CISDBOT")
from backtest.data import load_ltf  # noqa: E402
from backtest.sweep_atr_filter import compute_atr14  # noqa: E402
from cryptofish.adapters.features import daily_session_vwap  # noqa: E402

MAKER, TAKER = 0.00036, 0.0010
MIN_STOP = 0.0025
CONF_MIN = 5
POS_H = 6
WIN = 30
PAIRS = ["BTC", "ETH", "DOGE", "KAS", "ADA", "BNB", "LINK", "LTC", "XRP", "SOL"]

rows = []
for sym in PAIRS:
    for f in sorted(glob.glob(f"D:/PYTHON/CISDBOT/RUNS/filters_off_full/{sym}_tf8_*.pkl")):
        c = pickle.load(open(f, "rb"))
        sigs = {str(s.get("hash")): s for s in c.get("signals") or []}
        trades = [t for t in c.get("trades") or [] if t.get("entry_kind") == "LIMIT"]
        if not trades:
            continue
        year = int(str(c.get("since"))[:4])
        try:
            df1, _ = load_ltf(tf="1m", since=f"{year}-01-01", until=f"{year}-12-31", symbol=sym)
            d30, _ = load_ltf(tf="30m", since=f"{year}-01-01", until=f"{year}-12-31", symbol=sym)
        except Exception as e:
            print(f"  {sym} {year}: нет данных ({e!r})", flush=True)
            continue
        d30.index = pd.DatetimeIndex(d30.index)
        atr = compute_atr14(d30)
        vwap = daily_session_vwap(d30)
        d30_open_min = (d30.index.to_numpy(dtype="datetime64[ns]").astype("int64") // 60_000_000_000)
        atr_v = atr.to_numpy(dtype=float)
        vw_v = vwap.to_numpy(dtype=float)
        cl30 = d30["close"].to_numpy(dtype=float)
        ts = pd.DatetimeIndex(df1.index).to_numpy(dtype="datetime64[ns]").astype("int64") // 60_000_000_000
        hi = df1["high"].to_numpy(dtype=float)
        lo = df1["low"].to_numpy(dtype=float)
        cl = df1["close"].to_numpy(dtype=float)
        step = max(1, int(round(np.median(np.diff(ts)))))

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
            # vd на последнем ЗАКРЫТОМ к from_ts 30m-баре
            k = int(np.searchsorted(d30_open_min, t0 - 30, side="right")) - 1
            if k < 15 or not np.isfinite(atr_v[k]) or atr_v[k] <= 0 or not np.isfinite(vw_v[k]):
                continue
            vd = (cl30[k] - vw_v[k]) / atr_v[k]
            i0 = int(np.searchsorted(ts, t0, side="left"))
            if i0 >= len(ts):
                continue
            sl = slice(i0, min(len(ts), i0 + int(WIN / step) + 1))
            hit = np.where(lo[sl] <= entry)[0] if long else np.where(hi[sl] >= entry)[0]
            if len(hit) == 0:
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
                out, r = "tp", 1.0 - 2 * MAKER / sp
            elif i_sl != 10 ** 9:
                out, r = "sl", -1.0 - MAKER / sp - TAKER / sp
            else:
                px = float(cl[ks][-1])
                out = "time"
                r = ((px - entry) / (entry - stop) if long else (entry - px) / (stop - entry)) - MAKER / sp - TAKER / sp
            rows.append({"sym": sym, "year": year, "dir": t.get("direction"), "vd": vd,
                         "out": out, "r": r})

df = pd.DataFrame(rows)
df.to_pickle("D:/PYTHON/cisdbotbybit/RUNS/temp/vwap_recal_live_anchor.pkl")
print(f"сделок: {len(df)}")


def stat(name, d):
    if not len(d):
        print(f"  {name:26s}: —")
        return
    tp = int((d.out == "tp").sum()); sl = int((d.out == "sl").sum())
    wr = 100 * tp / max(1, tp + sl)
    print(f"  {name:26s}: n={len(d):5d} TP={tp:4d} SL={sl:4d} TIME={int((d.out=='time').sum()):4d} "
          f"WR={wr:5.1f}% ΣR={d.r.sum():+8.1f} avg={d.r.mean():+.3f}")


print()
print("=== LONG ===")
L = df[df["dir"] == "LONG"]
stat("все лонги", L)
stat("vd >= 0 (деплой)", L[L.vd >= 0])
stat("vd < 0 (отсекались)", L[L.vd < 0])
stat("vd <= -3 (старое правило)", L[L.vd <= -3])
stat("0 < vd <= 4", L[(L.vd > 0) & (L.vd <= 4)])
print()
print("=== SHORT ===")
S = df[df["dir"] == "SHORT"]
stat("все шорты", S)
stat("vd <= 0 (деплой)", S[S.vd <= 0])
stat("vd > 0 (отсекались)", S[S.vd > 0])
print()
print("=== комбо L vd>=0 + S vd<=0 против всех ===")
stat("все", df)
stat("гейт", pd.concat([L[L.vd >= 0], S[S.vd <= 0]]))
print()
print("=== по годам: гейт vs все (ΣR) ===")
for y in sorted(df.year.unique()):
    dy = df[df.year == y]
    g = pd.concat([dy[(dy["dir"] == "LONG") & (dy.vd >= 0)], dy[(dy["dir"] == "SHORT") & (dy.vd <= 0)]])
    print(f"  {y}: все {dy.r.sum():+8.1f} | гейт {g.r.sum():+8.1f} (n {len(g)}/{len(dy)})")

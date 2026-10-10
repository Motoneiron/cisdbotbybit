"""Цвет D/W-свечи на момент входа: живые сделки (16-21.09) vs бэк-паттерн (§34)."""
import numpy as np
import pandas as pd

LIVE = "D:/PYTHON/cisdbotbybit/RUNS/live_trades_tf8/LIVE_TRADES_tf8_30m-8H.csv"
D = "D:/PYTHON/cisdbotbybit/RUNS/temp"

df = pd.read_csv(LIVE, parse_dates=["entry_time"])
print("сделок всего:", len(df))

_cache = {}
def candles(sym):
    if sym not in _cache:
        d = (pd.read_csv(f"{D}/data_live_sep2026/{sym}USDT_5m_bybit.csv", parse_dates=["timestamp"])
             .set_index("timestamp").sort_index())
        d = d[~d.index.duplicated(keep="last")]
        _cache[sym] = d
    return _cache[sym]

rows = []
for _, t in df.iterrows():
    sym, ts = t.symbol_key, t.entry_time
    d = candles(sym)
    j = d.index.searchsorted(ts, side="right") - 1
    close_now = float(d["close"].iloc[j]) if j >= 0 else np.nan
    out = {}
    for rule, pref in (("W-MON", "w"), ("D", "dd")):
        o = d["open"].resample(rule, label="left", closed="left").first()
        pos = o.index.searchsorted(ts, side="right") - 1
        out[pref] = bool(close_now > o.iloc[pos]) if pos >= 0 else None
    r = dict(t)
    r.update(out)
    rows.append(r)

r = pd.DataFrame(rows)
r["d_side"] = np.where(r["direction"] == "LONG", r.dd == True, r.dd == False)
r["w_side"] = np.where(r["direction"] == "LONG", r.w == True, r.w == False)

print(f"\n{'id':<10}{'sym':<6}{'dir':<6}{'вход (UTC)':<17}{'D':<5}{'W':<5}{'статус':<12}{'net':>7}  Dсогл Wсогл")
for _, t in r.iterrows():
    d_col = "bull" if t.dd is True else ("bear" if t.dd is False else "?")
    w_col = "bull" if t.w is True else ("bear" if t.w is False else "?")
    net = f"{t.pnl_net:+.2f}" if pd.notna(t.pnl_net) else "—"
    print(f"{t.id:<10}{t.symbol_key:<6}{t["direction"]:<6}{str(t.entry_time)[:16]:<17}{d_col:<5}{w_col:<5}"
          f"{t.status:<12}{net:>7}  {'ЗА' if t.d_side else 'против':<5}{'ЗА' if t.w_side else 'против'}")

closed = r[r.status.astype(str).str.startswith("closed")].copy()
print(f"\n=== сводка (закрытые, n={len(closed)}), net = Σpnl_net USDT ===")
for name, m in (
    ("D ЗА сделку   ", closed.d_side),
    ("D ПРОТИВ      ", ~closed.d_side),
    ("W ЗА          ", closed.w_side),
    ("W ПРОТИВ      ", ~closed.w_side),
    ("D+W ЗА обе    ", closed.d_side & closed.w_side),
    ("D+W против обе", ~closed.d_side & ~closed.w_side),
):
    g = closed[m]
    tp = int((g.status == "closed_tp").sum()); sl = int((g.status == "closed_sl").sum()); tm = int((g.status == "closed_time").sum())
    net = float(g.pnl_net.sum())
    print(f"  {name}: n={len(g):>2} | TP {tp} SL {sl} TIME {tm} | Σnet {net:+.2f}")

print("\n=== комбо-квадранты ===")
for name, m in (
    ("D+W за       ", closed.d_side & closed.w_side),
    ("только D за  ", closed.d_side & ~closed.w_side),
    ("только W за  ", ~closed.d_side & closed.w_side),
    ("D+W против   ", ~closed.d_side & ~closed.w_side),
):
    g = closed[m]
    print(f"  {name}: n={len(g):>2} | Σnet {float(g.pnl_net.sum()):+.2f} | "
          f"TP {int((g.status=='closed_tp').sum())} SL {int((g.status=='closed_sl').sum())} TIME {int((g.status=='closed_time').sum())}")

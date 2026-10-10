"""Исход 8 живых лимиток по минутным свечам: 10 минут на вход, 12 часов в позиции."""
import pandas as pd

OUT = r"D:\PYTHON\cisdbotbybit\RUNS\temp\live_sep"
# scan time, sym, dir, entry, stop, tp, what live did
LIVE = [
    ("2026-09-24 01:45:00", "LTC", "SHORT", 61.82, 62.57, 61.07, "fill SL"),
    ("2026-09-24 02:15:00", "LINK", "LONG", 12.242, 12.17, 12.314, "cancel"),
    ("2026-09-24 02:20:00", "KAS", "LONG", 0.03832, 0.03796, 0.03868, "cancel"),
    ("2026-09-24 05:55:00", "LTC", "SHORT", 67.95, 69.34, 66.56, "cancel"),
    ("2026-09-24 14:50:00", "LINK", "SHORT", 12.525, 12.743, 12.307, "cancel"),
    ("2026-09-24 17:25:00", "KAS", "SHORT", 0.03989, 0.04075, 0.03903, "cancel"),
    ("2026-09-24 17:55:00", "SOL", "SHORT", 116.89, 117.72, 116.06, "cancel"),
    ("2026-09-25 01:35:00", "DOGE", "SHORT", 0.09595, 0.09695, 0.09495, "fill TP"),
]
MAKER, TAKER = 0.00036, 0.0010


def load(sym):
    df = pd.read_csv(f"{OUT}/{sym}USDT_1m.csv")
    df["dt"] = pd.to_datetime(df["timestamp"])
    return df.set_index("dt")[["open", "high", "low", "close"]]


def sim(df, scan, direction, entry, stop, tp):
    t0 = pd.Timestamp(scan)
    t1 = t0 + pd.Timedelta(minutes=10)
    window = df[(df.index >= t0) & (df.index < t1)]
    fill_ts = None
    for ts, bar in window.iterrows():
        if direction == "LONG" and float(bar.low) <= entry:
            fill_ts = ts
            break
        if direction == "SHORT" and float(bar.high) >= entry:
            fill_ts = ts
            break
    if fill_ts is None:
        return "no_fill", None
    end = fill_ts + pd.Timedelta(hours=12)
    path = df[(df.index >= fill_ts) & (df.index <= end)]
    sp = abs(entry - stop) / entry
    for ts, bar in path.iterrows():
        if direction == "LONG":
            sl = float(bar.low) <= stop
            tp_hit = float(bar.high) >= tp
        else:
            sl = float(bar.high) >= stop
            tp_hit = float(bar.low) <= tp
        if sl:
            gross = -1.0
            r = gross - MAKER / sp - TAKER / sp
            return f"sl {ts}", r
        if tp_hit:
            gross = 1.0
            r = gross - MAKER / sp - MAKER / sp
            return f"tp {ts}", r
    last = float(path.iloc[-1].close)
    gross = (last - entry) / (entry - stop) if direction == "LONG" else (entry - last) / (stop - entry)
    r = gross - MAKER / sp - TAKER / sp
    return f"time {path.index[-1]}", r


def main():
    cache = {}
    ok = 0
    for scan, sym, direction, entry, stop, tp, live in LIVE:
        if sym not in cache:
            cache[sym] = load(sym)
        outcome, r = sim(cache[sym], scan, direction, entry, stop, tp)
        match = (
            (live.startswith("cancel") and outcome == "no_fill")
            or (live == "fill SL" and outcome.startswith("sl"))
            or (live == "fill TP" and outcome.startswith("tp"))
        )
        ok += int(match)
        rtxt = "" if r is None else f" r={r:+.3f}"
        print(f"{'OK' if match else 'DIFF'} live={live:8} bt={outcome}{rtxt}  {sym} {direction} {scan}")
    print(f"matched {ok}/{len(LIVE)}")


if __name__ == "__main__":
    main()

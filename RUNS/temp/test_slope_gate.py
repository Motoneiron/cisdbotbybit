"""Приёмка тренд-гейта EMA3 1H.

Запуск: cd D:/PYTHON/cisdbotbybit && python RUNS/temp/test_slope_gate.py
"""
import asyncio
import os
import sys

import pandas as pd

sys.path.insert(0, ".")
import cisdbot as B  # noqa: E402

fails = []


def check(name, got, exp):
    ok = got == exp
    if not ok:
        fails.append(name)
    print(("OK   " if ok else "FAIL ") + name + f"  got={got!r} exp={exp!r}", flush=True)


TH = 0.02

print("=== 1. verdict _slope_filter_ok_hermes ===")
check("+0.05%/LONG ok", B._slope_filter_ok_hermes("LONG", 0.05, TH), True)
check("+0.05%/SHORT skip", B._slope_filter_ok_hermes("SHORT", 0.05, TH), False)
check("-0.05%/SHORT ok", B._slope_filter_ok_hermes("SHORT", -0.05, TH), True)
check("-0.05%/LONG skip", B._slope_filter_ok_hermes("LONG", -0.05, TH), False)
check("+0.01%/LONG ok (dead zone)", B._slope_filter_ok_hermes("LONG", 0.01, TH), True)
check("+0.01%/SHORT ok (dead zone)", B._slope_filter_ok_hermes("SHORT", 0.01, TH), True)
check("no data ok", B._slope_filter_ok_hermes("LONG", None, TH), True)

print()
print("=== 2. 1H bar closing exactly at anchor is still open ===")
idx = pd.date_range("2026-09-16 08:00:00", periods=6, freq="1h")
df = pd.DataFrame(
    {"open": 100.0, "high": 101.0, "low": 99.0, "close": [100, 101, 102, 103, 104, 105],
     "volume": 1.0},
    index=idx,
)
closed = B._closed_ohlcv_before(df, "2026-09-16 11:00:00", pd.Timedelta(hours=1), inclusive=False)
last_open = None if closed is None or len(closed) == 0 else str(closed.index[-1])
check("last closed at 11:00 is 09:00 (not 10:00)", last_open, "2026-09-16 09:00:00")
closed2 = B._closed_ohlcv_before(df, "2026-09-16 11:00:01", pd.Timedelta(hours=1), inclusive=False)
last2 = None if closed2 is None or len(closed2) == 0 else str(closed2.index[-1])
check("at 11:00:01 bar 10:00 is closed", last2, "2026-09-16 10:00:00")

print()
print("=== 3. fail-open if no data ===")


async def _none_ohlcv(*a, **k):
    return None

orig = B._get_slope_ohlcv_cached
B._get_slope_ohlcv_cached = _none_ohlcv
ok, slope, reason = asyncio.run(
    B._slope_gate_for_sig({"direction": "SHORT", "slope_as_of": "2026-09-16 11:00:00"}, "tf8")
)
B._get_slope_ohlcv_cached = orig
check("no OHLCV -> ok", ok, True)
check("no OHLCV -> slope is None", slope is None, True)
check("no OHLCV -> fail-open in reason", "fail-open" in reason, True)

print()
print("=== 4. tf8 profile ===")
prof = B._slope_profile_for_tf("tf8")
check("tf8 profile exists", prof is not None, True)
if prof:
    check("tf8 span=3", int(prof["span"]), 3)
    check("tf8 ohlcv=1h", prof["ohlcv_tf"], "1h")
check("slope_gate_enabled default", bool(B.CONFIG.get("slope_gate_enabled", True)), False)
check("gate threshold 0.02", B._slope_gate_threshold(), 0.02)

print()
print("=== 5. replay 14 trades: closed 1H (bot) vs forming (live_vs_trend) ===")
AGAINST_FORMING = {
    ("KAS", "LONG", "2026-09-16 07:09:13"),
    ("ETH", "SHORT", "2026-09-16 19:32:13"),
    ("LTC", "SHORT", "2026-09-16 19:32:13"),
    ("LINK", "SHORT", "2026-09-17 04:38:47"),
    ("XRP", "LONG", "2026-09-17 14:32:41"),
    ("LTC", "SHORT", "2026-09-17 19:30:00"),
}
TRADES = [
    ("ADA", "LONG", "2026-09-16 02:43:53"), ("KAS", "LONG", "2026-09-16 07:09:13"),
    ("BTC", "LONG", "2026-09-16 11:37:49"), ("SOL", "SHORT", "2026-09-16 13:14:59"),
    ("DOGE", "LONG", "2026-09-16 18:30:11"), ("BTC", "SHORT", "2026-09-16 18:38:32"),
    ("ETH", "SHORT", "2026-09-16 19:32:13"), ("LTC", "SHORT", "2026-09-16 19:32:13"),
    ("ADA", "LONG", "2026-09-16 20:01:04"), ("BNB", "SHORT", "2026-09-17 02:37:30"),
    ("LINK", "SHORT", "2026-09-17 04:38:47"), ("XRP", "LONG", "2026-09-17 14:32:41"),
    ("LINK", "SHORT", "2026-09-17 18:30:00"), ("LTC", "SHORT", "2026-09-17 19:30:00"),
]


def forming_slope(h1, ts):
    """Как live_vs_trend: последний бар с open <= t (включая незакрытый)."""
    s = B._slope_hermes_series(h1, 3)
    t = pd.Timestamp(ts)
    k = int(s.index.searchsorted(t, side="right")) - 1
    if k < 0:
        return None
    return float(s.iloc[k])


REC = os.path.join("RUNS", "temp", "data_recent")
n_closed = 0
n_form_match = 0
for sym, d, ts in TRADES:
    path = os.path.join(REC, f"{sym}USDT_5m_recent.csv")
    if not os.path.isfile(path):
        print(f"  skip {sym} {ts}: no csv")
        continue
    raw = pd.read_csv(path, parse_dates=["timestamp"])
    raw = raw.set_index("timestamp")
    raw.columns = [c.lower() for c in raw.columns]
    h1 = B._resample_ohlcv(raw, "1h")
    sl_c = B._slope_pct_from_ohlcv(h1, ts, span=3, ohlcv_tf="1h")
    sl_f = forming_slope(h1, ts)
    ok_c = B._slope_filter_ok_hermes(d, sl_c, TH) if sl_c is not None else True
    ok_f = B._slope_filter_ok_hermes(d, sl_f, TH) if sl_f is not None else True
    want = (sym, d, ts) in AGAINST_FORMING
    if sl_c is not None:
        n_closed += 1
    if sl_f is not None and (not ok_f) == want:
        n_form_match += 1
    sc = f"{sl_c:+7.3f}%" if sl_c is not None else "   n/a "
    sf = f"{sl_f:+7.3f}%" if sl_f is not None else "   n/a "
    print(
        f"  {ts} {sym:5s} {d:5s} closed={sc} {'SKIP' if not ok_c else 'pass':4s}  "
        f"forming={sf} {'SKIP' if not ok_f else 'pass':4s}  "
        f"live_vs={'SKIP' if want else 'pass'}"
    )

check("replay computed closed slope", n_closed >= 12, True)
check("forming lookup matches live_vs_trend labels", n_form_match >= 6, True)

print()
if fails:
    print(f"FAILED {len(fails)}: {fails}")
    sys.exit(1)
print("ALL OK")

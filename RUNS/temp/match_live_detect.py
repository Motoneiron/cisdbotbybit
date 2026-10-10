"""Прогон детектора живого бота по свечам 20-25 сент, сверка с журналом."""
from __future__ import annotations

import logging
import sys

import pandas as pd

sys.path.insert(0, r"D:\PYTHON\cisdbotbybit")
logging.disable(logging.CRITICAL)

import cisdbot as bot  # noqa: E402

PAIRS = ["LINK", "KAS"]
OUT = r"D:\PYTHON\cisdbotbybit\RUNS\temp\live_sep"

# Журнал: поставленные лимитки
LIVE = [
    ("LTC", "SHORT", 61.82, 62.57, "2026-09-24 01:40"),
    ("LINK", "LONG", 12.242, 12.17, "2026-09-24 02:10"),
    ("KAS", "LONG", 0.03832, 0.03796, "2026-09-24 02:15"),
    ("LTC", "SHORT", 67.95, 69.34, "2026-09-24 05:15"),
    ("LINK", "SHORT", 12.525, 12.743, "2026-09-24 14:45"),
    ("KAS", "SHORT", 0.03989, 0.04075, "2026-09-24 17:20"),
    ("SOL", "SHORT", 116.89, 117.72, "2026-09-24 17:20"),
    ("DOGE", "SHORT", 0.09595, 0.09695, "2026-09-25 01:30"),
]


def _key(sym, direction, entry, stop):
    return (sym, direction, round(float(entry), 5), round(float(stop), 5))


WIN = 300


def scan(sym: str) -> list[dict]:
    raw = pd.read_csv(f"{OUT}/{sym}USDT_1m.csv")
    raw["dt"] = pd.to_datetime(raw["timestamp"])
    m1 = raw.set_index("dt")[["open", "high", "low", "close", "volume"]]
    df5 = bot._resample_ohlcv(m1, "5m")
    bot.state.paper = True
    bot.state.sweep_candidates.clear()
    bot.state.htf_sweep_lock.clear()
    if hasattr(bot.state, "htf_sweep_validated"):
        bot.state.htf_sweep_validated.clear()
    seen: set = set()
    found = []
    htf = int(bot.CONFIG["tf7"]["htf_ratio"])
    with bot._use_symbol(sym):
        for i in range(120, len(df5)):
            sl = df5.iloc[max(0, i - (WIN - 1)) : i + 1]
            sigs = bot.detect_signals(
                sl, seen, htf_ratio=htf, tf_name="tf7",
                df_confirm=None, min_sweep_atr=bot._min_sweep_atr("tf7"),
            ) or []
            scan_ts = str(df5.index[i])[:19]
            for s in sigs:
                h = str(s.get("hash") or "")
                if not h or h in seen:
                    continue
                seen.add(h)
                e = float(s.get("entry") or 0)
                st = float(s.get("stop") or 0)
                stop_pct = abs(st - e) / e * 100.0 if e else 0
                ok_sw, why = bot._sweep_valid_for_setup(
                    sl, htf,
                    str(s.get("htf_time") or ""),
                    str(s.get("trigger_bar_time") or s.get("trigger_bar_at") or ""),
                    float(s.get("htf_sweep_level") or s.get("sweep_level") or 0),
                    str(s.get("direction") or ""),
                )
                found.append({
                    "sym": sym,
                    "direction": s.get("direction"),
                    "entry": e,
                    "stop": st,
                    "tp": float(s.get("tp") or 0),
                    "ts": str(s.get("timestamp") or "")[:19],
                    "trig": str(s.get("trigger_bar_time") or s.get("trigger_bar_at") or "")[:19],
                    "htf": str(s.get("htf_time") or "")[:19],
                    "scan": scan_ts,
                    "stop_pct": round(stop_pct, 3),
                    "min_stop": stop_pct >= 0.5,
                    "sweep_ok": bool(ok_sw),
                    "why": why[:80],
                })
    print(f"{sym} raw {len(found)}", flush=True)
    return found


def main():
    all_s = []
    for sym in PAIRS:
        all_s.extend(scan(sym))
    placed = [s for s in all_s if s["min_stop"] and s["sweep_ok"]]
    print("\n=== WOULD PLACE ===")
    for s in sorted(placed, key=lambda x: x["scan"]):
        if s["scan"] < "2026-09-23 16:00":
            continue
        print(
            f"{s['scan']} {s['sym']:4} {s['direction']:5} e={s['entry']} stop={s['stop']} "
            f"tp={s['tp']} trig={s['trig']} htf={s['htf']}"
        )
    live_keys = {_key(a, b, c, d) for a, b, c, d, _ in LIVE}
    got = {_key(s["sym"], s["direction"], s["entry"], s["stop"]) for s in placed}
    print("\nmatch", len(live_keys & got), "/", len(live_keys))
    print("missing", live_keys - got)
    extra = []
    for s in placed:
        if s["scan"] < "2026-09-23 16:00":
            continue
        k = _key(s["sym"], s["direction"], s["entry"], s["stop"])
        if k not in live_keys:
            extra.append(s)
    print("extra after bot up", len(extra))
    for s in extra:
        print(" ", s["scan"], s["sym"], s["direction"], s["entry"], s["stop"])


if __name__ == "__main__":
    main()

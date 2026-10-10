"""Ф1: регресс tf8 и сверка tf7 с каноном MSS_MAIN на окне SOL."""
import json
import logging
import pickle
import sys
import time

sys.path.insert(0, r"D:\PYTHON\cisdbotbybit")
logging.disable(logging.CRITICAL)

import pandas as pd

import cisdbot as bot

CSV = r"D:\databtcusdt\SOLUSDT-5m\SOLUSDT_5m_2026-06-01_2026-08-23.csv"
BEFORE = r"D:\PYTHON\cisdbotbybit\RUNS\temp\f1_tf8_before.json"
PKL = r"D:\PYTHON\cisdbotbybit\RUNS\temp\live_recon\recon_MSS_MAIN.pkl"


def load_df():
    df = pd.read_csv(CSV, usecols=["open_time", "open", "high", "low", "close", "volume"])
    df["dt"] = pd.to_datetime(df.open_time, unit="ms")
    return df.set_index("dt")[["open", "high", "low", "close", "volume"]]


def walk(df, tf_name, until):
    sub = df.loc[:until]
    bot.state.sweep_candidates.clear()
    bot.state.htf_sweep_lock.clear()
    seen = set()
    out = []
    htf = int(bot.CONFIG[tf_name]["htf_ratio"])
    for i in range(1000, len(sub)):
        sl = sub.iloc[max(0, i - 999) : i + 1]
        if tf_name == "tf8":
            work = bot._resample_ohlcv(sl, "30m")
            confirm = sl
            if work is None or len(work) < 20:
                continue
        else:
            work = sl
            confirm = None
            if len(work) < 50:
                continue
        sigs = bot.detect_signals(
            work, seen, htf_ratio=htf, tf_name=tf_name,
            df_confirm=confirm, min_sweep_atr=bot._min_sweep_atr(tf_name),
        ) or []
        for s in sigs:
            h = s.get("hash")
            if not h or h in seen:
                continue
            seen.add(h)
            out.append({
                "hash": h,
                "dir": s.get("direction"),
                "htf": str(s.get("htf_time")),
                "cisd": s.get("cisd_level"),
                "sweep": s.get("htf_sweep_level"),
                "entry": s.get("entry"),
                "stop": s.get("stop"),
                "tp": s.get("tp"),
                "confirm": str(s.get("confirm_bar_time") or ""),
                "soft": bool(s.get("soft_dow")),
                "filters": s.get("detect_filters"),
            })
    return out


def main():
    print("flags tf7", bot._detect_filter_flags("tf7"), "atr", bot._min_sweep_atr("tf7"))
    print("flags tf8", bot._detect_filter_flags("tf8"), "atr", bot._min_sweep_atr("tf8"))
    print("tf7 windows", bot.CONFIG["tf7"]["limit_h"], bot.CONFIG["tf7"]["position_h"],
          "shadow", bot.CONFIG["tf7"].get("shadow_only"))
    print("active", bot.ACTIVE_TF_KEYS, bot.SCAN_TF_KEYS)
    df = load_df()
    t0 = time.time()
    after = walk(df, "tf8", "2026-06-15 00:00:00")
    print(f"tf8 after {len(after)} sec {time.time()-t0:.1f}")
    before = json.load(open(BEFORE, encoding="utf-8"))
    bh = [x["hash"] for x in before]
    ah = [x["hash"] for x in after]
    print("tf8 hash equal", bh == ah, "before", len(bh), "after", len(ah))
    if bh != ah:
        print("only before", sorted(set(bh) - set(ah)))
        print("only after", sorted(set(ah) - set(bh)))
    soft_diff = sum(1 for b, a in zip(before, after) if bool(b.get("soft")) != bool(a.get("soft")))
    print("tf8 soft_dow diffs", soft_diff)

    t0 = time.time()
    tf7 = walk(df, "tf7", "2026-06-15 00:00:00")
    print(f"tf7 bot {len(tf7)} sec {time.time()-t0:.1f}")
    print("tf7 sample filters", tf7[0]["filters"] if tf7 else None)

    try:
        rec = pickle.load(open(PKL, "rb"))
    except Exception as e:
        print("pkl", e)
        rec = {}
    trades = rec.get("trades") or []
    print("pkl trades", len(trades), "keys", list(trades[0].keys())[:20] if trades else None)
    # min-stop контрольный срез по эталонным сделкам
    if trades:
        def stop_pct(t):
            e = float(t.get("entry") or t.get("entry_price") or 0)
            s = float(t.get("stop") or t.get("stop_price") or 0)
            if e <= 0 or s <= 0:
                return None
            return abs(e - s) / e * 100.0

        def r_of(t):
            for k in ("r", "R", "pnl_r", "result_r"):
                if t.get(k) is not None:
                    return float(t[k])
            return None

        rows = []
        for t in trades:
            sp = stop_pct(t)
            if sp is None:
                continue
            rows.append((sp, r_of(t)))
        with_r = [x for x in rows if x[1] is not None]
        print("trades with stop", len(rows), "with R", len(with_r))
        if with_r:
            keep = [x for x in with_r if x[0] >= 0.5]
            drop = [x for x in with_r if x[0] < 0.5]
            print(
                f"min_stop 0.5%: keep {len(keep)} sumR {sum(x[1] for x in keep):.2f} | "
                f"drop {len(drop)} sumR {sum(x[1] for x in drop):.2f} | "
                f"all {len(with_r)} sumR {sum(x[1] for x in with_r):.2f}"
            )


if __name__ == "__main__":
    main()

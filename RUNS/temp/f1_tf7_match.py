"""Сверка детекта бота tf7 с эталоном recon_MSS_MAIN (SOL, тот же 1m→5m)."""
import logging
import pickle
import sys

sys.path.insert(0, r"D:\PYTHON\cisdbotbybit")
logging.disable(logging.CRITICAL)

import pandas as pd

import cisdbot as bot

CSV = r"D:\PYTHON\cisdbotbybit\RUNS\temp\live_recon\SOLUSDT_1m_recon.csv"
PKL = r"D:\PYTHON\cisdbotbybit\RUNS\temp\live_recon\recon_MSS_MAIN.pkl"


def k_full(direction, htf, cisd, stop):
    h = str(pd.Timestamp(htf))[:16]
    return (direction, h, round(float(cisd), 2), round(float(stop), 2))


def k_htf(direction, htf):
    return (direction, str(pd.Timestamp(htf))[:16])


def main():
    raw = pd.read_csv(CSV)
    raw["dt"] = pd.to_datetime(raw["timestamp"])
    m1 = raw.set_index("dt")[["open", "high", "low", "close", "volume"]]
    df5 = bot._resample_ohlcv(m1, "5m")
    print("5m", len(df5), df5.index[0], df5.index[-1])

    rec = pickle.load(open(PKL, "rb"))
    model = []
    for s in rec["signals"]:
        model.append(k_full(s["direction"], s["htf_time"], s["cisd_level"], s["stop"]))
    model_set = set(model)
    model_htf = set(k_htf(a, b) for a, b, _, _ in model_set)
    print("model signals", len(model_set))

    bot.state.sweep_candidates.clear()
    bot.state.htf_sweep_lock.clear()
    seen = set()
    bot_keys = []
    htf = int(bot.CONFIG["tf7"]["htf_ratio"])
    n_det = 0
    for i in range(1000, len(df5)):
        closed = df5.index[i - 1]
        if pd.Timestamp(closed) < pd.Timestamp("2026-06-20"):
            continue
        if not bot._is_detect_step_ts(pd.Timestamp(closed), 5, 12):
            continue
        sl = df5.iloc[max(0, i - 999) : i + 1]
        n_det += 1
        sigs = bot.detect_signals(
            sl, seen, htf_ratio=htf, tf_name="tf7",
            df_confirm=None, min_sweep_atr=bot._min_sweep_atr("tf7"),
        ) or []
        for s in sigs:
            hsh = s.get("hash")
            if not hsh or hsh in seen:
                continue
            seen.add(hsh)
            bot_keys.append(k_full(s["direction"], s["htf_time"], s["cisd_level"], s["stop"]))
        if n_det % 200 == 0:
            print("det", n_det, "sigs", len(bot_keys), "at", closed, flush=True)

    bset = set(bot_keys)
    bhtf = set(k_htf(a, b) for a, b, _, _ in bset)
    both = model_set & bset
    both_h = model_htf & bhtf
    print("detect calls", n_det, "bot signals", len(bset))
    print(f"exact cisd+stop {len(both)}/{len(model_set)} = {100*len(both)/len(model_set):.1f}%")
    print(f"dir+htf {len(both_h)}/{len(model_htf)} = {100*len(both_h)/len(model_htf):.1f}%")
    only_m = sorted(model_htf - bhtf)
    only_b = sorted(bhtf - model_htf)
    print("only model", len(only_m))
    for x in only_m[:8]:
        print("  M", x)
    print("only bot", len(only_b))
    for x in only_b[:8]:
        print("  B", x)


if __name__ == "__main__":
    main()

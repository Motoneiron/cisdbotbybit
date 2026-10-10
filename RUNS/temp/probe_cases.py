"""Пробник кейсов: где физически случился вход (до/после close конфирма) у live-only и canon-only сделок."""
import sys

sys.path.insert(0, r"D:/PYTHON/cisdbotbybit")
sys.path.insert(0, r"D:/PYTHON/cisdbotbybit/RUNS/temp")

import logging

logging.disable(logging.CRITICAL)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import cisdbot as bot  # noqa: E402
import live_filt_big as lfb  # noqa: E402

bot.CONFIG["tf7"]["detect_filters"] = {"atr_enabled": False, "vol_enabled": False, "d_enabled": True}

df1 = lfb.load_1m(lfb.PATHS["SOL"], "2024-01-01", "2024-02-15")
df5 = bot._resample_ohlcv(df1, "5m")
print("data:", df1.shape, df5.shape, df5.index[0], "->", df5.index[-1], flush=True)

CASES = [
    ("live-only", "2024-01-01 11:25:00", "SHORT"),
    ("live-only", "2024-01-04 09:35:00", "LONG"),
    ("live-only", "2024-01-05 17:20:00", "LONG"),
    ("live-only", "2024-01-06 22:00:00", "LONG"),
    ("live-only", "2024-01-07 14:35:00", "SHORT"),
    ("live-only", "2024-01-11 12:15:00", "SHORT"),
    ("canon-only", "2024-01-07 02:20:00", "SHORT"),
    ("canon-only", "2024-01-10 00:20:00", "LONG"),
    ("canon-only", "2024-01-14 14:20:00", "LONG"),
    ("canon-only", "2024-01-18 03:20:00", "LONG"),
    ("canon-only", "2024-01-23 22:20:00", "LONG"),
]

for tag, ts_s, want in CASES:
    ts = pd.Timestamp(ts_s)
    try:
        i = df5.index.get_loc(ts)
    except KeyError:
        print("!! нет бара", ts_s)
        continue
    bot.state.sweep_candidates.clear()
    if hasattr(bot.state, "htf_sweep_lock"):
        bot.state.htf_sweep_lock.clear()
    sl = df5.iloc[i - 299 : i + 1]
    sigs = bot.detect_signals(sl, set(), htf_ratio=240, tf_name="tf7", df_confirm=None, min_sweep_atr=0.0) or []
    sigs = [s for s in sigs if str(s.get("direction")) == want]
    print("=" * 110)
    print(f"{tag} | бар {ts_s} | {want} | сигналов на баре: {len(sigs)}")
    for s in sigs:
        e = float(s.get("entry") or 0)
        st = float(s.get("stop") or 0)
        tbt = str(s.get("trigger_bar_time") or "")
        cbt = str(s.get("confirm_bar_time") or "")
        htf_s = str(s.get("htf_time") or "")
        hsh = str(s.get("hash") or "")[:16]
        lvl = float(s.get("htf_sweep_level") or s.get("sweep_level") or 0)
        try:
            ok_sw, why = bot._sweep_valid_for_setup(sl, 240, htf_s, tbt, lvl, want)
        except Exception as exc:
            ok_sw, why = "ERR", str(exc)[:60]
        print(f"   entry={e} stop={st} trig={tbt} confirm={cbt} htf={htf_s} hash={hsh} гейт={ok_sw}")
        # первое касание entry в пределах [ts−15м, ts+45м]
        lo = ts - pd.Timedelta(minutes=15)
        hi = ts + pd.Timedelta(minutes=45)
        w = df1[(df1.index >= lo) & (df1.index < hi)]
        if want == "LONG":
            hh = w[w.low <= e]
        else:
            hh = w[w.high >= e]
        if len(hh):
            fh = hh.index[0]
            rel_open = (fh - ts).total_seconds() / 60
            line = f"      касание {fh}  Δopen_скана={rel_open:+.1f} мин"
            if cbt:
                cc = pd.Timestamp(cbt) + pd.Timedelta(minutes=5)
                line += f"  Δclose_конфирма={(fh - cc).total_seconds()/60:+.1f} мин"
            print(line)
            if len(hh) > 1:
                print(f"      ...всего касаний в окне: {len(hh)}")
        else:
            print("      касаний entry в ±окне НЕТ")

"""Probe2: окно выдачи сигнала детектом + сверка хэшей с каноном + тайминги касаний."""
import pickle
import sys

sys.path.insert(0, r"D:/PYTHON/cisdbotbybit")
sys.path.insert(0, r"D:/PYTHON/cisdbotbybit/RUNS/temp")

import logging

logging.disable(logging.CRITICAL)

import pandas as pd  # noqa: E402

import cisdbot as bot  # noqa: E402
import live_filt_big as lfb  # noqa: E402

bot.CONFIG["tf7"]["detect_filters"] = {"atr_enabled": False, "vol_enabled": False, "d_enabled": True}

df1 = lfb.load_1m(lfb.PATHS["SOL"], "2023-12-28", "2024-02-15")
df5 = bot._resample_ohlcv(df1, "5m")
CAN = pickle.load(open("tf7_abl/ABL_MSS_MAIN_SOL_2024.pkl", "rb"))
print("data:", df1.shape, flush=True)

CASES = [
    ("live-only", "2024-01-01 11:25:00", "SHORT"),
    ("live-only", "2024-01-04 09:35:00", "LONG"),
    ("live-only", "2024-01-05 17:20:00", "LONG"),
    ("live-only", "2024-01-07 14:35:00", "SHORT"),
    ("canon-only", "2024-01-07 02:20:00", "SHORT"),
    ("canon-only", "2024-01-14 14:20:00", "LONG"),
    ("canon-only", "2024-01-18 03:20:00", "LONG"),
    ("canon-only", "2024-01-23 22:20:00", "LONG"),
]

for tag, ts_s, want in CASES:
    ts = pd.Timestamp(ts_s)
    i0 = df5.index.get_loc(ts)
    print("#" * 112)
    print(f"{tag} | бар {ts_s} | {want}")
    for r in CAN:
        rt = pd.Timestamp(r["created_ts"])
        if abs((rt - ts).total_seconds()) <= 3600 * 3:
            print(f"   [канон] created={r['created_ts']} entry={r['entry_ts']} {r['direction']} {r['outcome']} hash={r['hash']}")
    for i in range(i0 - 18, i0 + 13):
        sl = df5.iloc[max(0, i - 299) : i + 1]
        sigs = bot.detect_signals(sl, set(), htf_ratio=240, tf_name="tf7", df_confirm=None, min_sweep_atr=0.0) or []
        for s in sigs:
            if str(s.get("direction")) != want:
                continue
            cbt = str(s.get("confirm_bar_time") or "")
            if not cbt:
                continue
            c = pd.Timestamp(cbt)
            if abs((c - ts).total_seconds()) > 3600 * 5:
                continue
            print(f"   i={i} barn={df5.index[i]} hash={str(s.get('hash') or '')[:16]} cbt={cbt} entry={s.get('entry')} trig={s.get('trigger_bar_time')}")
    # тайминги касаний entry вокруг ts: [-20, +30) минут, все
    t_lo = ts - pd.Timedelta(minutes=20)
    t_hi = ts + pd.Timedelta(minutes=30)
    print(f"   -- касания entry ({want}):")
    # entry неизвестен до детекта... печатаем по последнему найденному сигналу? Соберём все entry из вывода выше — для простоты берём из сигналов повторно:
    ents = set()
    for i in range(i0 - 18, i0 + 13):
        sl = df5.iloc[max(0, i - 299) : i + 1]
        sigs = bot.detect_signals(sl, set(), htf_ratio=240, tf_name="tf7", df_confirm=None, min_sweep_atr=0.0) or []
        for s in sigs:
            if str(s.get("direction")) == want and s.get("confirm_bar_time"):
                c = pd.Timestamp(str(s["confirm_bar_time"]))
                if abs((c - ts).total_seconds()) <= 3600 * 5:
                    ents.add((float(s.get("entry") or 0), str(s.get("confirm_bar_time")), str(s.get("trigger_bar_time")), str(s.get("hash") or "")[:16]))
    w = df1[(df1.index >= t_lo) & (df1.index < t_hi)]
    for e, cbt_s, tbt_s, hsh in sorted(ents):
        if not e:
            continue
        if want == "LONG":
            hh = w[w.low <= e]
        else:
            hh = w[w.high >= e]
        times = [str(t) for t in hh.index[:6]]
        cc = (pd.Timestamp(cbt_s) + pd.Timedelta(minutes=5)) if cbt_s else None
        print(f"     entry={e} cbt={cbt_s} close_конф={cc} hash={hsh}")
        print(f"       первые касания: {times}")
        if cc is not None:
            inL = [t for t in hh.index if ts <= t < ts + pd.Timedelta(minutes=10)]
            inC = [t for t in hh.index if cc <= t < cc + pd.Timedelta(minutes=10)]
            print(f"       в live-окне [scan, +10): {[str(t) for t in inL[:4]]}")
            print(f"       в канон-окне [close_конф, +10): {[str(t) for t in inC[:4]]}")
    del w

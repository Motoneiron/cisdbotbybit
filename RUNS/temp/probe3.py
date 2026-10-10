"""Probe3: один и тот же детект с A/V OFF (как live) против A/V ON (как канон) на кейсах."""
import sys

sys.path.insert(0, r"D:/PYTHON/cisdbotbybit")
sys.path.insert(0, r"D:/PYTHON/cisdbotbybit/RUNS/temp")

import logging

logging.disable(logging.CRITICAL)

import pandas as pd  # noqa: E402

import cisdbot as bot  # noqa: E402
import live_filt_big as lfb  # noqa: E402

df1 = lfb.load_1m(lfb.PATHS["SOL"], "2023-12-28", "2024-02-15")
df5 = bot._resample_ohlcv(df1, "5m")
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


def runs(ts, want, atr_on, vol_on):
    """Возвращает список выдач (bar, hash, cbt) при данных флагах фильтров."""
    bot.CONFIG["tf7"]["detect_filters"] = {
        "atr_enabled": atr_on,
        "vol_enabled": vol_on,
        "d_enabled": True,
    }
    ts = pd.Timestamp(ts)
    i0 = df5.index.get_loc(ts)
    out = []
    last = None
    for i in range(i0 - 18, i0 + 13):
        sl = df5.iloc[max(0, i - 299) : i + 1]
        sigs = bot.detect_signals(sl, set(), htf_ratio=240, tf_name="tf7", df_confirm=None) or []
        for s in sigs:
            if str(s.get("direction")) != want:
                continue
            cbt = str(s.get("confirm_bar_time") or "")
            if not cbt:
                continue
            c = pd.Timestamp(cbt)
            if abs((c - ts).total_seconds()) > 3600 * 5:
                continue
            h = str(s.get("hash") or "")[:16]
            if last != h:
                out.append({"first": str(df5.index[i]), "hash": h, "cbt": cbt, "entry": s.get("entry"), "last": str(df5.index[i])})
                last = h
            else:
                out[-1]["last"] = str(df5.index[i])
    return out, i0


for tag, ts_s, want in CASES:
    print("#" * 112)
    print(f"{tag} | {ts_s} | {want}")
    on_list, i0 = runs(ts_s, want, True, True)
    off_list, _ = runs(ts_s, want, False, False)
    print("  A/V ON  (как канон):")
    for r in on_list:
        print(f"     {r['first']} .. {r['last']} | hash={r['hash']} cbt={r['cbt']} entry={r['entry']}")
    if not on_list:
        print("     -- НЕ ВИДЕН --")
    print("  A/V OFF (как live):")
    for r in off_list:
        print(f"     {r['first']} .. {r['last']} | hash={r['hash']} cbt={r['cbt']} entry={r['entry']}")
    if not off_list:
        print("     -- НЕ ВИДЕН --")
    # скоры фич (по OFF-сигналам)
    seen_h = set()
    for r in off_list:
        if r["hash"] in seen_h:
            continue
        seen_h.add(r["hash"])
        i = df5.index.get_loc(pd.Timestamp(r["first"]))
        sl = df5.iloc[max(0, i - 299) : i + 1]
        sig = None
        for s in bot.detect_signals(sl, set(), htf_ratio=240, tf_name="tf7", df_confirm=None) or []:
            if str(s.get("hash") or "").startswith(r["hash"]) and str(s.get("direction")) == want:
                sig = s
                break
        if sig is None:
            continue
        f = lfb._feats(sig, sl)
        print(f"     фичи {r['hash']}: sw={f['sw'] if f['sw'] is None else round(f['sw'],3)} vol={f['vol'] if f['vol'] is None else round(f['vol'],2)} soft={f['soft']} touches={f['touches']}")

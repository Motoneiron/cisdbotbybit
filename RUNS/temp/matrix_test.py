"""matrix_test.py — 2x2: бар(conf, conf+1) x фильтры(A/V on, off). MEXC-мир (канон)."""
import logging
import sys

sys.path.insert(0, r"D:/PYTHON/CISDBOT")
logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(message)s")

import pandas as pd  # noqa: E402
import cisdbot as bot  # noqa: E402

df = pd.read_csv(
    r"D:/databtcusdt/SOLUSDT-5m/SOLUSDT_5m_full_hdr.csv",
    usecols=["open_time", "open", "high", "low", "close", "volume"],
)
df.index = pd.to_datetime(df.pop("open_time"), unit="ms")
df = df.astype(float).sort_index()

BARS = ["2024-01-01 11:20:00", "2024-01-01 11:25:00", "2024-01-13 06:40:00", "2024-01-13 06:45:00",
        "2024-01-05 17:20:00", "2024-01-05 17:25:00"]
HF = int(bot.CONFIG["tf7"]["htf_ratio"])

for bar_s in BARS:
    i = int(df.index.searchsorted(pd.Timestamp(bar_s)))
    sl = df.iloc[i - 199 : i + 1]
    print(f"\n##### бар {bar_s} (посл.бар окна)")
    for mode, flt in (("default/AVD", None), ("AV-off", {"atr_enabled": False, "vol_enabled": False, "d_enabled": True})):
        if flt is None:
            bot.CONFIG["tf7"].pop("detect_filters", None)
        else:
            bot.CONFIG["tf7"]["detect_filters"] = flt
        out = bot.detect_signals(sl, set(), htf_ratio=HF, tf_name="tf7", df_confirm=None) or []
        print(f"  [{mode}]: {len(out)} сигналов")
        for s in out:
            print(f"     {s.get('direction')} cbt={s.get('confirm_bar_time')} e={s.get('entry')}")
bot.CONFIG["tf7"].pop("detect_filters", None)
print("\ndone")

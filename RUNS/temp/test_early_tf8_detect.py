"""Критическая проверка: находит ли детектор tf8 сигнал НА 5м-скане (в середине 30м бара)?

Кейс: KAS SHORT, конфирм 2026-09-12 05:10 UTC, бот нашёл сигнал на 30м-закрытии в 05:30.
Проверяем: если бы детект шёл в 05:15 / 05:20 / 05:25 — нашёл бы сигнал?
"""
import sys

sys.path.insert(0, r"D:/PYTHON/cisdbotbybit")
sys.path.insert(0, r"D:/PYTHON")
sys.path.insert(0, r"D:/PYTHON/CISDBOT")

import importlib.util

import pandas as pd

spec = importlib.util.spec_from_file_location("cisdbot_mod", r"D:/PYTHON/cisdbotbybit/cisdbot.py")
bot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bot)

import ccxt

ex = ccxt.bybit({"defaultType": "swap"})
o = ex.fetch_ohlcv("KAS/USDT:USDT", "5m", limit=1000)
df5 = pd.DataFrame(o, columns=["ts", "open", "high", "low", "close", "volume"])
df5["dt"] = pd.to_datetime(df5.ts, unit="ms", utc=True)
df5 = df5.set_index("dt")[["open", "high", "low", "close", "volume"]]
df5.index = df5.index.tz_localize(None)
print("5m данные:", df5.index[0], "..", df5.index[-1], f"({len(df5)})")

# target: конфирм 2026-09-12 05:10, 30м бар [05:00-05:30)
for cut in ("2026-09-12 05:15", "2026-09-12 05:20", "2026-09-12 05:25", "2026-09-12 05:30"):
    df5c = df5[df5.index <= pd.Timestamp(cut)].copy()
    df30 = bot._resample_ohlcv(df5c, "30m")
    print(f"\n=== Скан {cut} UTC: df5 баров={len(df5c)}, df30 баров={len(df30)} "
          f"(последний 30м: {df30.index[-1]}) ===")
    try:
        sigs = bot.detect_signals(
            df30, set(), htf_ratio=480, tf_name="tf8",
            df_confirm=df5c, min_sweep_atr=0.0,
        )
        sigs = sigs or []
        print(f"сигналов: {len(sigs)}")
        for s in sigs[:3]:
            print(f"  {s.get('direction')} entry={s.get('entry')} conf={s.get('confirm_bar_time')} "
                  f"htf={s.get('htf_time')} type={s.get('type')}")
    except Exception as e:
        print(f"ОШИБКА: {e!r}")

"""Дамп CONFIG MEXC-бота: есть ли tf8 и что в его полях."""
import sys

sys.path.insert(0, r"D:/PYTHON")
sys.path.insert(0, r"D:/PYTHON/CISDBOT")

import logging
logging.disable(logging.ERROR)

import cisdbot as bot  # noqa: E402

cfg = getattr(bot, "CONFIG", None)
print("CONFIG type:", type(cfg).__name__)
if isinstance(cfg, dict):
    keys = list(cfg.keys())
    print("keys:", keys)
    tf8 = cfg.get("tf8")
    if tf8 is not None:
        print("tf8 fields:", sorted(tf8.keys()))
        print("tf8 confirm_timeframe:", repr(tf8.get("confirm_timeframe")))
        print("tf8 timeframe:", repr(tf8.get("timeframe")), "| htf_ratio:", tf8.get("htf_ratio"))
    print("tf7 confirm:", repr((cfg.get("tf7") or {}).get("confirm_timeframe")))
    print("_confirm_timeframe_for('tf8') =", repr(bot._confirm_timeframe_for("tf8")))
    print("_confirm_timeframe_for('tf8_mss5') =", repr(bot._confirm_timeframe_for("tf8_mss5")))

"""Дамп структуры профилей tf7/tf6 в CONFIG MEXC-бота (образец для tf8_mss5)."""
import sys

sys.path.insert(0, r"D:/PYTHON")
sys.path.insert(0, r"D:/PYTHON/CISDBOT")

import logging
logging.disable(logging.ERROR)

import cisdbot as bot  # noqa: E402

for name in ("tf6", "tf7"):
    print(name, "=", bot.CONFIG.get(name))

"""Проверка ФАКТА фикса на боевых данных: позиция ADA из shadow_positions.json
+ тот самый бар 02:00-02:30 (low=0.1921), который убил сделку.

Сравниваем СТАРУЮ логику (как было) и НОВУЮ (задеплоенную).
Запуск на сервере из изолированной папки: PYTHONPATH=/opt/cisdbotbybit venv/bin/python3 ...
"""
import json
import sys

sys.path.insert(0, ".")

import cisdbot as B   # noqa: E402

POS = json.load(open("/opt/cisdbotbybit/shadow_positions.json"))
raw = [x for x in POS if x["id"] == "Lecdf997a"][0]
p = B.Position.from_dict(raw)

cached = {"time": "2026-09-16 02:00:00", "low": 0.1921, "high": 0.1940, "close": 0.1940}
price = 0.1945   # реальная цена в момент «стопа» 02:44:00 UTC

print("позиция:", p.id, p.direction, "entry", p.entry_price, "stop", p.stop_price,
      "tf", p.tf, "closed_bar_at", p.closed_bar_at, "entry_time", p.entry_time)

# старая логика (до 8730b70)
bar_low = cached.get("low")
old_sl = price <= p.stop_price or (bar_low is not None and bar_low <= p.stop_price)
print("СТАРАЯ логика  sl_hit =", old_sl)

# новая логика (задеплоена)
tp_hit, sl_hit, src, bar_t = B._paper_position_level_hits(p, price, cached)
print("НОВАЯ логика  tp_hit =", tp_hit, " sl_hit =", sl_hit, " src =", repr(src), " bar =", bar_t)
print("гейт бара:", B._shadow_ohlc_usable_for_position(p, cached))
print("bоt.log_dir:", B.BASE_DIR)
print("ИТОГ:", "фикс работает" if (old_sl and not sl_hit) else "ПРОВЕРИТЬ ВРУЧНУЮ")

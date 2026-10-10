"""Юнит-проверка фикса «pre-entry bar» в paper SL/TP (коммит 8730b70).

Без сети: конструируем Position + кэш бара и проверяем вердикты хелперов.
Порядок возврата _paper_position_level_hits: (tp_hit, sl_hit, exit_src, exit_bar_time).
Запуск: cd D:/PYTHON/cisdbotbybit && python RUNS/temp/test_paper_level_hits.py
"""
import datetime as dt
import sys

sys.path.insert(0, ".")

import cisdbot as B   # noqa: E402

fails = []


def check(name, got, exp):
    ok = got == exp
    if not ok:
        fails.append(name)
    print(("OK   " if ok else "FAIL ") + name + f"  got={got!r} exp={exp!r}")


def hits(p, px, cached):
    tp, sl, src, bt = B._paper_position_level_hits(p, px, cached)
    return {"tp": tp, "sl": sl, "src": src, "bar": bt}


def mk_pos(entry, stop, tp, direction, entry_time, closed_bar_at, px_min=None, px_max=None):
    p = B.Position(
        pos_id="T", direction=direction, entry_price=entry, stop_price=stop,
        tp_price=tp, contracts=1, entry_time=entry_time,
        exit_time=entry_time + dt.timedelta(hours=6), tf="tf8", trade_num=1,
    )
    p.symbol_key = "ADA"
    p.closed_bar_at = closed_bar_at
    p.px_min_since_entry = px_min if px_min is not None else entry
    p.px_max_since_entry = px_max if px_max is not None else entry
    return p


T = dt.datetime(2026, 9, 16, 2, 43, 53)          # момент входа (naive UTC)

# 1. Кейс ADA: бар 02:00 закрылся ДО входа, его low = уровень стопа -> НЕ срабатывает
cached_old = {"time": "2026-09-16 02:00:00", "low": 0.1921, "high": 0.1940, "close": 0.1940}
p = mk_pos(0.1946, 0.1921, 0.1971, "LONG", T, "2026-09-16 02:00:00")
r = hits(p, 0.1945, cached_old)
check("ADA: бар до входа не триггерит", (r["tp"], r["sl"]), (False, False))

# 2. Бар целиком после входа -> работает
cached_new = {"time": "2026-09-16 03:00:00", "low": 0.1919, "high": 0.1950, "close": 0.1945}
r = hits(p, 0.1945, cached_new)
check("бар после входа триггерит стоп", (r["tp"], r["sl"]), (False, True))
check("источник = bar + время бара", (r["src"], r["bar"]), ("bar", "2026-09-16 03:00:00"))

# 3. Экстремум с момента входа (live-поллы)
p3 = mk_pos(0.1946, 0.1921, 0.1971, "LONG", T, "2026-09-16 02:00:00", px_min=0.1919, px_max=0.1946)
r = hits(p3, 0.1945, cached_old)
check("экстремум с входа триггерит стоп", (r["tp"], r["sl"]), (False, True))
check("источник = since_entry", r["src"], "since_entry")

# 4. Старая позиция без closed_bar_at: OHLC-ветка выключена
p4 = mk_pos(0.1946, 0.1921, 0.1971, "LONG", T, "")
r = hits(p4, 0.1945, {"time": "2026-09-16 03:00:00", "low": 0.18, "high": 0.20})
check("старая запись без closed_bar_at: бар не используется", (r["tp"], r["sl"]), (False, False))

# 5. Бар, который частично до входа (02:30 < 02:43:53) -> не используется
check("частично до входа (02:30) не используется",
      B._shadow_ohlc_usable_for_position(p, {"time": "2026-09-16 02:30:00", "low": 0.18, "high": 0.20}), False)
# 6. Бар = closed_bar_at -> не используется; строго позже входа -> используется
check("бар == closed_bar_at не используется",
      B._shadow_ohlc_usable_for_position(p, {"time": "2026-09-16 02:00:00"}), False)
check("бар позже входа используется",
      B._shadow_ohlc_usable_for_position(p, {"time": "2026-09-16 03:00:00"}), True)
check("кэш без time -> False", B._shadow_ohlc_usable_for_position(p, {}), False)
check("closed_bar_at пустой -> False", B._shadow_ohlc_usable_for_position(p4, {"time": "2026-09-16 03:00:00"}), False)

# 7. SHORT зеркально: тейк ниже, стоп выше
s = mk_pos(100.0, 101.0, 99.0, "SHORT", T, "2026-09-16 02:00:00")
r = hits(s, 100.2, {"time": "2026-09-16 03:00:00", "low": 99.5, "high": 101.5})
check("SHORT: бар после входа триггерит стоп", (r["tp"], r["sl"]), (False, True))
r = hits(s, 100.2, {"time": "2026-09-16 03:00:00", "low": 98.5, "high": 100.5})
check("SHORT: бар после входа триггерит тейк", (r["tp"], r["sl"]), (True, False))
r = hits(s, 100.2, {"time": "2026-09-16 02:00:00", "low": 95.0, "high": 105.0})
check("SHORT: бар до входа не триггерит", (r["tp"], r["sl"]), (False, False))

# 8. round-trip сериализации новых полей
p.exit_src, p.exit_bar_time = "bar", "2026-09-16 03:00:00"
back = B.Position.from_dict(p.to_dict())
check("round-trip новых полей",
      (back.closed_bar_at, back.px_min_since_entry, back.px_max_since_entry, back.exit_src, back.exit_bar_time),
      (p.closed_bar_at, p.px_min_since_entry, p.px_max_since_entry, p.exit_src, p.exit_bar_time))

# 9. журнальная запись содержит новые поля
rec = B._position_journal_record(p, event="closed")
check("journal: exit_src/exit_bar_time", (rec.get("exit_src"), rec.get("exit_bar_time")), ("bar", "2026-09-16 03:00:00"))

print()
print("ИТОГ:", "ВСЁ ОК" if not fails else f"ПРОВАЛЕНО {len(fails)}: {fails}")

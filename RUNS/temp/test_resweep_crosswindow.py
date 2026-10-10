"""Проверка b9d3d3f: пересвип глубже снимает старых кандидатов по ВСЕМ окнам,
равенство пробоем не считается, более глубокий живой кандидат не перебивается мелким.
"""
import sys

sys.path.insert(0, "D:/PYTHON/cisdbotbybit")
import cisdbot as B   # noqa: E402

SK = "DOGE"
B.active_symbol_key = lambda *a, **k: SK


def cand(tf, direction, htf, sweep, ext, trig="2026-09-17 08:30:00"):
    return {
        "tf": tf, "direction": direction, "htf_time": htf, "sweep_level": sweep,
        "trigger_extreme": ext, "trigger_time": trig, "symbol_key": SK,
    }


def keys():
    return sorted(k.split("|", 1)[1] for k in B.state.sweep_candidates)


print("=== 1. DOGE-кейс: свип 0.08098 (окно 00:00), затем глубже 0.08132 (окно 08:00) ===")
B.state.sweep_candidates.clear()
B.state._resweep_cancel_queue.clear()
B._upsert_sweep_candidate(B._cand_key("tf8", "SHORT", "2026-09-17 00:00:00", SK),
                          cand("tf8", "SHORT", "2026-09-17 00:00:00", 0.08098, 0.08166))
print("после 1-го:", keys())
B._upsert_sweep_candidate(B._cand_key("tf8", "SHORT", "2026-09-17 08:00:00", SK),
                          cand("tf8", "SHORT", "2026-09-17 08:00:00", 0.08132, 0.08166))
print("после 2-го:", keys())
ok1 = "tf8|SHORT|2026-09-17 00:00:00" not in keys() and "tf8|SHORT|2026-09-17 08:00:00" in keys() \
    and "tf8|SHORT|2026-09-17 08:00:00" in keys()
print("РЕЗУЛЬТАТ 1 (старый снят, новый на месте):", ok1)

print()
print("=== 2. Равный уровень — пробоем НЕ считается, оба живут ===")
B.state.sweep_candidates.clear()
B._upsert_sweep_candidate(B._cand_key("tf8", "LONG", "2026-09-17 00:00:00", SK),
                          cand("tf8", "LONG", "2026-09-17 00:00:00", 0.08132, 0.08110))
B._upsert_sweep_candidate(B._cand_key("tf8", "LONG", "2026-09-17 08:00:00", SK),
                          cand("tf8", "LONG", "2026-09-17 08:00:00", 0.08132, 0.08110))
print("кандидаты:", keys())
ok2 = len(B.state.sweep_candidates) == 2
print("РЕЗУЛЬТАТ 2 (равенство не снимает):", ok2)

print()
print("=== 3. Мелкий кандидат не перебивает живого глубокого ===")
B.state.sweep_candidates.clear()
B._upsert_sweep_candidate(B._cand_key("tf8", "SHORT", "2026-09-17 08:00:00", SK),
                          cand("tf8", "SHORT", "2026-09-17 08:00:00", 0.08132, 0.08166))
B._upsert_sweep_candidate(B._cand_key("tf8", "SHORT", "2026-09-17 16:00:00", SK),
                          cand("tf8", "SHORT", "2026-09-17 16:00:00", 0.08098, 0.08166))
print("кандидаты:", keys())
ok3 = len(B.state.sweep_candidates) == 1 and "tf8|SHORT|2026-09-17 08:00:00" in keys()
print("РЕЗУЛЬТАТ 3 (мелкий не добавился):", ok3)

print()
print("=== 4. Глубже по экстремуму (при равном уровне свипа) — снимает ===")
B.state.sweep_candidates.clear()
B._upsert_sweep_candidate(B._cand_key("tf8", "SHORT", "2026-09-17 00:00:00", SK),
                          cand("tf8", "SHORT", "2026-09-17 00:00:00", 0.08132, 0.08150))
B._upsert_sweep_candidate(B._cand_key("tf8", "SHORT", "2026-09-17 08:00:00", SK),
                          cand("tf8", "SHORT", "2026-09-17 08:00:00", 0.08132, 0.08166))
print("кандидаты:", keys())
ok4 = len(B.state.sweep_candidates) == 1 and "tf8|SHORT|2026-09-17 08:00:00" in keys()
print("РЕЗУЛЬТАТ 4:", ok4)

print()
print("ИТОГ:", "ВСЁ ОК" if (ok1 and ok2 and ok3 and ok4) else "ЕСТЬ ПРОБЛЕМЫ")

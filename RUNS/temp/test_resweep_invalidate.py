"""Юнит-проверка: более глубокий свип в другом HTF-окне снимает старого кандидата.

Равенство пробоем не считается. Позиции не создаём.
Запуск: python RUNS/temp/test_resweep_invalidate.py
"""
import sys

sys.path.insert(0, ".")
import cisdbot as B  # noqa: E402

fails = []


def check(name, got, exp):
    ok = got == exp
    if not ok:
        fails.append(name)
    print(("OK   " if ok else "FAIL ") + name + f"  got={got!r} exp={exp!r}")


def mk(htf, sweep, ext, direction="SHORT", sk="DOGE", tf="tf8"):
    return {
        "tf": tf,
        "symbol_key": sk,
        "direction": direction,
        "htf_time": htf,
        "type": "bearish" if direction == "SHORT" else "bullish",
        "sweep_level": sweep,
        "trigger_idx": 1,
        "trigger_time": htf,
        "trigger_extreme": ext,
    }


saved_cands = dict(B.state.sweep_candidates)
saved_q = list(B.state._resweep_cancel_queue)
B.state.sweep_candidates = {}
B.state._resweep_cancel_queue = []
try:
    k0 = B._cand_key("tf8", "SHORT", "2026-09-17 00:00:00", "DOGE")
    k1 = B._cand_key("tf8", "SHORT", "2026-09-17 08:00:00", "DOGE")
    B._upsert_sweep_candidate(k0, mk("2026-09-17 00:00:00", 0.08098, 0.08110))
    check("окно A живёт", k0 in B.state.sweep_candidates, True)

    B._upsert_sweep_candidate(k1, mk("2026-09-17 08:00:00", 0.08132, 0.08166))
    check("окно A снято более глубоким B", k0 in B.state.sweep_candidates, False)
    check("окно B стоит", k1 in B.state.sweep_candidates, True)

    B.state.sweep_candidates = {}
    B._upsert_sweep_candidate(k0, mk("2026-09-17 00:00:00", 0.08132, 0.08166))
    B._upsert_sweep_candidate(k1, mk("2026-09-17 08:00:00", 0.08132, 0.08166))
    check("равный уровень: A жив", k0 in B.state.sweep_candidates, True)
    check("равный уровень: B жив", k1 in B.state.sweep_candidates, True)

    check("SHORT глубже строго выше", B._is_resweep_level("SHORT", 0.08132, 0.08098), True)
    check("SHORT равенство не пробой", B._is_resweep_level("SHORT", 0.08098, 0.08098), False)
    check("LONG глубже строго ниже", B._is_resweep_level("LONG", 0.19, 0.191), True)
    check("LONG равенство не пробой", B._is_resweep_extreme("LONG", 0.19, 0.19), False)

    B.state.sweep_candidates = {}
    B._upsert_sweep_candidate(k1, mk("2026-09-17 08:00:00", 0.08132, 0.08166))
    B._upsert_sweep_candidate(k0, mk("2026-09-17 00:00:00", 0.08098, 0.08110))
    check("мелкий после глубокого не встаёт", k0 in B.state.sweep_candidates, False)
    check("глубокий остаётся", k1 in B.state.sweep_candidates, True)

    k2 = B._cand_key("tf8", "SHORT", "2026-09-16 16:00:00", "DOGE")
    B.state.sweep_candidates = {
        k2: mk("2026-09-16 16:00:00", 0.08100, 0.08120),
        k1: mk("2026-09-17 08:00:00", 0.08132, 0.08166),
    }
    B._upsert_sweep_candidate(k0, mk("2026-09-17 00:00:00", 0.08110, 0.08130))
    check("средний не снимает мелкого если живёт более глубокий", k2 in B.state.sweep_candidates, True)
    check("средний не встаёт рядом с глубоким", k0 in B.state.sweep_candidates, False)
    check("глубокий на месте", k1 in B.state.sweep_candidates, True)
finally:
    B.state.sweep_candidates = saved_cands
    B.state._resweep_cancel_queue = saved_q

print()
if fails:
    print("FAILED:", fails)
    sys.exit(1)
print("all ok", 9)

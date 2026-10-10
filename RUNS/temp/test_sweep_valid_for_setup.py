"""Мягкий гейт свипа: пробой триггером + close HTF обратно за уровень."""
import importlib.util
import sys

import pandas as pd

sys.path.insert(0, r"D:/PYTHON/cisdbotbybit")
spec = importlib.util.spec_from_file_location(
    "cisdbot_mod", r"D:/PYTHON/cisdbotbybit/cisdbot.py",
)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

failed = 0


def check(name, cond, detail=""):
    global failed
    if not cond:
        failed += 1
    extra = f"  {detail}" if detail else ""
    print(f"{'OK' if cond else 'FAIL'}: {name}{extra}")


def _bars(rows):
    idx = pd.DatetimeIndex([r[0] for r in rows])
    return pd.DataFrame(
        {
            "open": [r[1] for r in rows],
            "high": [r[2] for r in rows],
            "low": [r[3] for r in rows],
            "close": [r[4] for r in rows],
            "volume": [1.0] * len(rows),
        },
        index=idx,
    )


# 15m × HTF 60m. Окно 00:00 high=100, окно 01:00 свип на 01:00, 02:00 — следующее.
base = [
    ("2026-09-16 00:00", 99.5, 100.0, 99.0, 99.6),
    ("2026-09-16 00:15", 99.6, 100.0, 99.1, 99.5),
    ("2026-09-16 00:30", 99.5, 100.0, 99.0, 99.4),
    ("2026-09-16 00:45", 99.4, 100.0, 99.0, 99.5),
    ("2026-09-16 01:00", 99.5, 101.0, 99.2, 99.7),  # trigger SHORT
    ("2026-09-16 01:15", 99.7, 100.4, 99.3, 99.6),
    ("2026-09-16 01:30", 99.6, 100.5, 99.2, 99.5),
    ("2026-09-16 01:45", 99.5, 100.3, 99.1, 99.4),
    ("2026-09-16 02:00", 99.4, 100.2, 99.0, 99.3),
]
df_ok = _bars(base)
ok, why = m._sweep_valid_for_setup(
    df_ok, 60, "2026-09-16 01:00:00", "2026-09-16 01:00:00", 100.0, "SHORT",
)
check("пробой + close обратно — ок", ok is True, why)

df_open = _bars(base[:-1])
ok, why = m._sweep_valid_for_setup(
    df_open, 60, "2026-09-16 01:00:00", "2026-09-16 01:00:00", 100.0, "SHORT",
)
check("окно не закрыто — не режем", ok is True, why)

# close окна остался выше уровня (нет rejection)
no_rej = list(base)
no_rej[7] = ("2026-09-16 01:45", 99.5, 100.8, 99.1, 100.4)
df_no_rej = _bars(no_rej)
ok, why = m._sweep_valid_for_setup(
    df_no_rej, 60, "2026-09-16 01:00:00", "2026-09-16 01:00:00", 100.0, "SHORT",
)
check("close не вернулся за уровень — skip", ok is False, why)

# триггер не пробил
no_pierce = list(base)
no_pierce[4] = ("2026-09-16 01:00", 99.5, 100.0, 99.2, 99.7)
df_no_pierce = _bars(no_pierce)
ok, why = m._sweep_valid_for_setup(
    df_no_pierce, 60, "2026-09-16 01:00:00", "2026-09-16 01:00:00", 100.0, "SHORT",
)
check("триггер не пробил — skip", ok is False, why)

# позже в том же окне более глубокий экстремум
stolen = list(base)
stolen[6] = ("2026-09-16 01:30", 99.6, 102.0, 99.2, 99.5)
df_stolen = _bars(stolen)
ok, why = m._sweep_valid_for_setup(
    df_stolen, 60, "2026-09-16 01:00:00", "2026-09-16 01:00:00", 100.0, "SHORT",
)
check("триггер не экстремум окна — skip", ok is False, why)

ok, why = m._sweep_valid_for_setup(
    df_ok, 60, "", "2026-09-16 01:00:00", 100.0, "SHORT",
)
check("нет htf — не режем", ok is True, why)

if failed:
    print(f"\nFAILED: {failed}")
    sys.exit(1)
print("\nALL OK")

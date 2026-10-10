"""tf8 confirm = 30m; XRP-like live gate skips implicit MARKET."""
import importlib.util
import sys

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


check("tf8 без confirm_timeframe", "confirm_timeframe" not in m.CONFIG["tf8"])
check("_confirm_timeframe_for(tf8) is None", m._confirm_timeframe_for("tf8") is None)
check("SCAN только tf8", m.SCAN_TF_KEYS == ("tf8",))

# XRP  LONG: live already through CISD
cisd = 1.2675
live = 1.2627
confirm = 1.2700  # close бара ещё «выше» — старый гейт бы пропустил
check(
    "confirm ещё retrace",
    m._is_retrace_at_creation("LONG", cisd, confirm) is True,
)
check(
    "live уже не retrace (XRP)",
    m._is_retrace_at_creation("LONG", cisd, live) is False,
)
bad = [
    k for k, v in (("confirm", confirm), ("live", live))
    if v > 0 and not m._is_retrace_at_creation("LONG", cisd, v)
]
check("гейт ловит live", bad == ["live"], f"bad={bad}")

# нет live → только confirm; деградация
bad2 = [
    k for k, v in (("confirm", confirm), ("live", 0.0))
    if v > 0 and not m._is_retrace_at_creation("LONG", cisd, v)
]
check("без live не скипаем по рынку", bad2 == [])

# pac == entry → fill-страховка скипает
check(
    "pac==entry не retrace",
    m._is_retrace_at_creation("LONG", 100.0, 100.0) is False,
)

if failed:
    print(f"\nFAILED: {failed}")
    sys.exit(1)
print("\nALL OK")

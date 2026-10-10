import importlib.util
import sys
from datetime import datetime

sys.path.insert(0, r"D:/PYTHON/cisdbotbybit")
sys.path.insert(0, r"D:/PYTHON")

spec = importlib.util.spec_from_file_location("cisdbot_mod", "D:/PYTHON/cisdbotbybit/cisdbot.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class FakePL2:
    closed_bar_at = ""
    created_at = datetime(2026, 9, 12, 17, 0, 16)  # naive UTC (как utcnow())


cached_old = {"time": "2026-09-12 16:30:00+00:00"}
cached_new = {"time": "2026-09-12 17:00:00+00:00"}
print("fallback старый бар (16:30):", m._shadow_ohlc_usable_for_fill(FakePL2(), cached_old), "<- ожидаем False")
print("fallback новый бар (17:00):", m._shadow_ohlc_usable_for_fill(FakePL2(), cached_new), "<- ожидаем True")
print("utcnow() naive?", m.utcnow().tzinfo is None)

# и полный сценарий BNB: closed_bar_at = 19:30 МСК = 16:30 UTC
class FakeBNB:
    closed_bar_at = "2026-09-12 19:30:00+03:00"
    created_at = datetime(2026, 9, 12, 17, 0, 16)


print("BNB старое закрытие:", m._shadow_ohlc_usable_for_fill(FakeBNB(), cached_old), "<- False (не фантомим)")
print("BNB новый бар:", m._shadow_ohlc_usable_for_fill(FakeBNB(), cached_new), "<- True")

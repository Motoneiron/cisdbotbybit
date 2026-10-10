"""Проверка фикса bc432a5: поймает ли новый лок ADA-кейс (равный экстремум триггера).

Воспроизводим ключи так, как их строит код:
 1) первый сетап ADA 16.09 21:00 МСК: signal htf_s=08:00, trigger 17:30, ext=0.1901, sweep=0.1921
    -> _mark_htf_sweep_consumed(htf_time="2026-09-16 08:00:00", ...)
 2) новый кандидат 23:00 МСК: signal htf_s=16:00, trigger 18:00, ext=0.1901, sweep=0.1903
    -> detect_signals строит ключ _htf_sweep_lock_key(..., htf_time=htf_s=16:00) и ищет в state.htf_sweep_lock
Плюс вариант «ключ по окну ТРИГГЕРА» (floor(trigger, 480)).
"""
import sys

sys.path.insert(0, "D:/PYTHON/cisdbotbybit")
import cisdbot as B   # noqa: E402

B.active_symbol_key = lambda *a, **k: "ADA"

# 1) ставим лок как первый сетап
B._mark_htf_sweep_consumed(
    "tf8", "LONG", "2026-09-16 08:00:00",
    trigger_extreme=0.1901, sweep_level=0.1921,
    stop=0.1901, tp=0.1945, trigger_idx=166,
    persist=False, symbol_key="ADA",
)
print("лок(и) в state после первого сетапа:")
for k in B.state.htf_sweep_lock:
    print("   ", k)

# 2) ключ, который построит detect_signals для нового кандидата
k_new = B._htf_sweep_lock_key("tf8", "LONG", 0.1903, symbol_key="ADA",
                              htf_time="2026-09-16 16:00:00")
print("\nключ нового кандидата (htf=16:00):", k_new)
lock = B.state.htf_sweep_lock.get(k_new)
print("лок найден:", lock is not None)
if lock:
    fresh = 0.1901
    deeper = B._is_resweep_extreme("LONG", fresh, lock["trigger_extreme"])
    print("пересвип (глубже)?", deeper, "-> сигнал", "СОЗДАН" if deeper else "ЗАБЛОКИРОВАН")
else:
    print("=> лок НЕ найден -> гард «ждём пересвип» не срабатывает -> сигнал СОЗДАН")

# 3) вариант: ключ по окну ТРИГГЕРА
k_trig_old = B._htf_sweep_lock_key("tf8", "LONG", 0.1921, symbol_key="ADA",
                                   htf_time="2026-09-16 16:00:00")
k_trig_new = B._htf_sweep_lock_key("tf8", "LONG", 0.1903, symbol_key="ADA",
                                   htf_time="2026-09-16 16:00:00")
print("\nвариант «окно триггера»: старый", k_trig_old)
print("вариант «окно триггера»: новый ", k_trig_new, "| уровни совпадут?", k_trig_old == k_trig_new)

# 4) как изменилась бы картина при скоупe уровня до целых (старая схема .0f)
print("\nстарая схема ключа (sweep=0, без окна) для сравнения:")
print("   store:", f"ADA|tf8|LONG|sweep={B._round_sweep_level(0.1921, 'ADA'):.0f}")
print("   lookup:", f"ADA|tf8|LONG|sweep={B._round_sweep_level(0.1903, 'ADA'):.0f}")

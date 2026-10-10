"""Проверка: tf7-кэши (confirm=1m в CONFIG) несут ли confirm_timeframe='1m' в сигналах."""
import glob
import pickle
from collections import Counter

files = sorted(glob.glob(r"D:/PYTHON/CISDBOT/RUNS/filters_off_full/*tf7*.pkl"))
print("tf7 cache files:", len(files))
for f in files[:4]:
    print(" ", f.split("/")[-1])
if files:
    c = pickle.load(open(files[0], "rb"))
    sigs = c.get("signals") or []
    print(files[0].split("/")[-1], "signals:", len(sigs))
    print("  confirm_timeframe:", dict(Counter(str(s.get("confirm_timeframe")) for s in sigs[:5000])))

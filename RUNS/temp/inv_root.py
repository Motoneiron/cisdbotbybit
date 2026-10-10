"""inv_root.py — инвентаризация корня live_tf/*.pkl после инцидента с OUT_DIR (28.09).

Читает каждый файл: время, размер, число строк, ключи записей — чтобы понять,
какому прогону (tf8 / tf7e13_002 / ...) принадлежит файл.
"""
import glob
import os
import pickle
import time

ROOT = "live_tf"
files = sorted(glob.glob(os.path.join(ROOT, "*.pkl")))
print(f"Всего pkl в корне live_tf/: {len(files)}")
for f in files:
    st = os.stat(f)
    mt = time.strftime("%H:%M:%S", time.localtime(st.st_mtime))
    with open(f, "rb") as fh:
        rows = pickle.load(fh)
    r0 = rows[0] if rows else {}
    if isinstance(r0, dict):
        keys = sorted(r0.keys())
    else:
        keys = type(r0).__name__
    extra = ""
    if isinstance(r0, dict):
        for k in ("mode", "MODE", "profile", "tf", "gate", "sl_gate", "skip_gate", "htf_ok", "htf_ratio"):
            if k in r0:
                extra += f" {k}={r0[k]!r}"
    print(f"{os.path.basename(f):16} {st.st_size:>7}B {mt} n={len(rows):>4}{extra}")
print()
print("keys примера:", sorted(rows[0].keys()) if rows and isinstance(rows[0], dict) else "n/a")

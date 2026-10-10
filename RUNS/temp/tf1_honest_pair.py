"""tf1_honest_pair.py — честный tf1 sl15(sp21) на ОДНОЙ паре (быстрая проверка якорей).

Гоняет live_tf_grid.run_symbol в одном процессе (без Pool) — годится для одной пары
или смоука, когда не нужен полный 6-парный конфиг.

Якоря (как в tf7-честном перегоне 30.09):
  lc — наклон на последнем ЗАКРЫТОМ 15m-баре к моменту решения (i-1), без 5-мин загляда
  cc — наклон на баре конфирма (jj-1)

Режим идентичен tf1sl15sp21 (min_stop=1.5, sl_gate span21 thr0.02% по 15m, A/V/D on,
min_sweep 0.40), меняется ТОЛЬКО якорь: cb (лукап) -> lc/cc (честный).

Usage:
  python tf1_honest_pair.py lc SOL          # SOL, 3 года (2024/2025/2026)
  python tf1_honest_pair.py cc SOL
  python tf1_honest_pair.py lc SOL smoke    # смоук: ADA, месяц (2024-06)

Результаты: live_tf/tf1sl15sp21_<anchor>/<SYM>_<year>.pkl
"""
import sys

sys.path.insert(0, r"D:\PYTHON\cisdbotbybit\RUNS\temp")
import live_tf_grid as g

anchor = (sys.argv[1] if len(sys.argv) > 1 else "lc").lower()
sym = (sys.argv[2] if len(sys.argv) > 2 else "SOL").upper()

mode = f"tf1sl15sp21_{anchor}"
g.MODES[mode] = {
    "profile": "tf1",
    "min_stop": 1.5,
    "sl_gate": (21, 0.0002, "15m", anchor),
}

g.MODE = mode
if len(sys.argv) > 3 and sys.argv[3].lower() == "smoke":
    g.SMOKE = True
    g.OUT_DIR = "smoke_" + mode
    print(f"===== SMOKE {mode} (ADA, 2024-06) =====", flush=True)
    print(g.run_symbol("ADA"), flush=True)
else:
    g.SMOKE = False
    g.OUT_DIR = mode
    print(f"===== {mode} pair={sym} anchor={anchor} =====", flush=True)
    print(g.run_symbol(sym), flush=True)

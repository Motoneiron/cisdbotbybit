# -*- coding: utf-8 -*-
"""Карта HTF на НЕсрезанном (nofilter) потоке: полные room-разрезы.

Вход: RUNS/cache/nofilter_summary.csv (31 537 сигналов; для 22 944 есть HTF-фичи).
Метрика качества сигнала q: r (taken) или r_cf (если взяли бы; per-signal, без busy).
Выход: RUNS/NOFILTER_MAP_ANALYSIS_2026-10-09.md
"""
import numpy as np
import pandas as pd

CSV = r"D:\PYTHON\cisdbotbybit\RUNS\cache\nofilter_summary.csv"
OUT = r"D:\PYTHON\cisdbotbybit\RUNS\NOFILTER_MAP_ANALYSIS_2026-10-09.md"

df = pd.read_csv(CSV)
df["taken"] = df["taken"].astype(bool)
df["q"] = np.where(df["taken"], df["r"], df["r_cf"])
df["out_q"] = np.where(df["taken"], df["outcome"], df["outcome_cf"])
df["year"] = df["scan"].astype(str).str[:4]

BUCKETS = ["<0.25", "0.25-0.5", "0.5-1", "1-2", "2-3", ">3", "нет"]


def rb(v):
    if pd.isna(v):
        return "нет"
    if v < 0.25:
        return "<0.25"
    if v < 0.5:
        return "0.25-0.5"
    if v < 1.0:
        return "0.5-1"
    if v < 2.0:
        return "1-2"
    if v < 3.0:
        return "2-3"
    return ">3"


df["room"] = df["nearest_opposing_R"].map(rb)
df["room_int"] = df["nearest_internal_R"].map(rb)
df["room_ext"] = df["nearest_external_R"].map(rb)


def stat(g):
    n = len(g)
    if n == 0:
        return None
    tp = int((g["out_q"] == "tp").sum())
    sl = int((g["out_q"] == "sl").sum())
    tm = int((g["out_q"] == "time").sum())
    rr = g["q"].astype(float)
    sd = rr.std(ddof=1) if n > 1 else 0.0
    ci = (round(rr.mean() - 1.96 * sd / np.sqrt(n), 3), round(rr.mean() + 1.96 * sd / np.sqrt(n), 3)) if n > 1 else ("-", "-")
    return {"n": n, "tp": tp, "sl": sl, "tm": tm,
            "wr": round(tp / n * 100, 1),
            "sumR": round(rr.sum(), 1), "avgR": round(rr.mean(), 4),
            "ci": f"[{ci[0]},{ci[1]}]"}


def fmt(s):
    if not s:
        return "—"
    return f"{s['n']} / {s['wr']}% / {s['sumR']:+.1f}R / {s['avgR']:+.3f} / {s['ci']}"


def table(dfg, col):
    rows = []
    for b in BUCKETS:
        s = stat(dfg[dfg[col] == b])
        rows.append([b, fmt(s)])
    return rows


def md(headers, rows):
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(x) for x in r) + " |")
    return "\n".join(out)


L = []
L.append("# Карта HTF на НЕсрезанном потоке (nofilter, 09.10.2026)")
L.append("")
with_ctx = int((df["taken"] | df["r_cf"].notna()).sum())
L.append(f"Сигналов всего: {len(df)}; с HTF-картой: {with_ctx}")
L.append(f"Метрика q: r для взятых (busy-механика) / r_cf для остальных (per-signal).")
L.append("")

# --- 1. taken-поток (busy) по карте
t = df[df["taken"] & df["r"].notna()]
L.append("## 1. Поток без фильтров (taken, busy) — корзины room")
L.append("")
L.append(md(["корзина", "n / WR / ΣR / avgR / CI95"], table(t, "room")))
L.append("")
L.append("По годам (n / avgR):")
L.append("")
yr = []
for y in ("2024", "2025", "2026"):
    cells = [y]
    for b in BUCKETS:
        g = t[(t["year"] == y) & (t["room"] == b)]
        s = stat(g)
        cells.append(f"{s['n']} / {s['avgR']}" if s else "—")
    yr.append(cells)
L.append(md(["год"] + BUCKETS, yr))
L.append("")
leg = []
for lg in ("LONG", "SHORT"):
    cells = [lg]
    for b in BUCKETS:
        s = stat(t[(t["direction"] == lg) & (t["room"] == b)])
        cells.append(f"{s['n']} / {s['avgR']}" if s else "—")
    leg.append(cells)
L.append(md(["нога"] + BUCKETS, leg))
L.append("")

# --- 2. per-signal q (все сигналы с исходом) по карте
qq = df[df["q"].notna() & df["room"].notna()]
L.append("## 2. Все сигналы с исходом (per-signal q, без busy) — корзины room")
L.append("")
L.append(md(["корзина", "n / WR / ΣR / avgR / CI95"], table(qq, "room")))
L.append("")
yr2 = []
for y in ("2024", "2025", "2026"):
    cells = [y]
    for b in BUCKETS:
        s = stat(qq[(qq["year"] == y) & (qq["room"] == b)])
        cells.append(f"{s['n']} / {s['avgR']}" if s else "—")
    yr2.append(cells)
L.append(md(["год"] + BUCKETS, yr2))
L.append("")

# --- 3. гейт x карта
L.append("## 3. Гейт × карта (per-signal q): avgR (n)")
L.append("")
g_rows = []
for gr, name in ((True, "гейт бы ОТСЁК"), (False, "гейт пропускал")):
    cells = [name]
    for b in BUCKETS:
        g = qq[(qq["gate_rej"] == gr) & (qq["room"] == b)]
        s = stat(g)
        cells.append(f"{s['avgR']:+.3f} ({s['n']})" if s else "—")
    g_rows.append(cells)
L.append(md(["гейт \\ room"] + BUCKETS, g_rows))
L.append("")

# --- 4. internal / external
L.append("## 4. Внутренняя (FVG) и внешняя (свинги+PDH/PWH) ликвидность — per-signal q")
L.append("")
L.append("**Внутренняя:**")
L.append("")
L.append(md(["корзина", "n / WR / ΣR / avgR / CI95"], table(qq, "room_int")))
L.append("")
L.append("**Внешняя:**")
L.append("")
L.append(md(["корзина", "n / WR / ΣR / avgR / CI95"], table(qq, "room_ext")))
L.append("")

# --- 5. маленькая справка: для сравнения — база (кандидат) по taken
base = pd.read_csv(r"D:\PYTHON\cisdbotbybit\RUNS\cache\htf_context_summary.csv")
bt = base[base["taken"] == True].copy()
bt["rbk"] = bt["nearest_opposing_obstacle_R"].map(rb)
L.append("## 5. Для сравнения — БАЗА (кандидат v2, taken 998), те же корзины")
L.append("")
rows5 = []
for b in BUCKETS:
    g = bt[bt["rbk"] == b]
    if len(g):
        rr = g["r"].astype(float)
        wr = (g["outcome"] == "tp").sum() / len(g) * 100
        rows5.append([b, f"{len(g)} / {wr:.1f}% / {rr.sum():+.1f}R / {rr.mean():+.3f}"])
    else:
        rows5.append([b, "—"])
L.append(md(["корзина", "n / WR / ΣR / avgR"], rows5))
L.append("")

with open(OUT, "w", encoding="utf-8") as f:
    f.write("\n".join(L))
print("\n".join(L[:60]))
print("\n...saved:", OUT)

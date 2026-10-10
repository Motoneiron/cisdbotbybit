# -*- coding: utf-8 -*-
"""Аудит отчётов 10.10: htf_open_window + htf_wick_level. Сверка цифр и причинности."""
import glob
import importlib.util
import os
import pickle
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, r"D:\PYTHON\cisdbotbybit")

OW = r"D:\PYTHON\cisdbotbybit\RUNS\cache\htf_open_window.csv"
WK = r"D:\PYTHON\cisdbotbybit\RUNS\cache\htf_wick_level.csv"
NF = r"D:\PYTHON\cisdbotbybit\RUNS\cache\nofilter_summary.csv"
NF_DIR = r"D:\PYTHON\cisdbotbybit\RUNS\temp\live_tf_htfctx_nf\rows_tf1v2_nofilter"
BASE_DIR = r"D:\PYTHON\cisdbotbybit\RUNS\temp\live_tf_htfctx\rows_tf1v2"

ow = pd.read_csv(OW)
wk = pd.read_csv(WK)
nf = pd.read_csv(NF)
print("ROWS ow/wk/nf:", len(ow), len(wk), len(nf))

print("\n========== [OW] open window ==========")
print("[OW] n1 NaN:", int(ow.n1_pct.isna().sum()))
print("[OW] >5R (старая пустота):", int((ow.n1_R > 5).sum()), round((ow.n1_R > 5).mean() * 100, 1), "%")
print("[OW] medians n1_pct/n1_R/n2_pct/n2_R:",
      round(ow.n1_pct.median(), 2), round(ow.n1_R.median(), 2),
      round(ow.n2_pct.median(), 2), round(ow.n2_R.median(), 2))

t = ow[ow.taken].copy()
print("[OW] taken:", len(t), "| passed:", int((~ow.gate_rej).sum()), "| cut:", int(ow.gate_rej.sum()))
print("[OW] taken n1_pct==0.0 (straddle):", int((t.n1_pct == 0.0).sum()))

def bucket(v):
    if pd.isna(v):
        return -1
    for i, e in enumerate([0.5, 1, 2, 3, 5, 8]):
        if v < e:
            return i
    return 6

t["b"] = t.n1_pct.map(bucket)
print("[OW] §1 taken buckets: n / WR / avgR / med_sp / med_R")
for i in list(range(7)) + [-1]:
    g = t[t.b == i]
    if len(g):
        print(f"   b{i}: {len(g)} / {round((g.outcome=='tp').mean()*100,1)}% / {round(g.q.mean(),3)}"
              f" / {round(g.sp.median()*100,2)}% / {round(g.n1_R.median(),2)}")
p = ow[~ow.gate_rej].copy()
p["b"] = p.n1_pct.map(bucket)
g = p[p.b == 2]
print("[OW] §3 gate-passed 1-2%: n", len(g), "avgR", round(g.q.mean(), 3))
for i in [1, 4]:
    g = p[p.b == i]
    if len(g):
        print(f"[OW] §3 b{i}: n {len(g)} avgR {round(g.q.mean(),3)} CI({round(g.q.mean()-1.96*g.q.std(ddof=1)/np.sqrt(len(g)),3)},{round(g.q.mean()+1.96*g.q.std(ddof=1)/np.sqrt(len(g)),3)})")
print("[OW] §5 sum types:", int(t.n1_type.fillna('нет').value_counts().sum()))

print("\n========== [WK] wick-level ==========")
wk = wk.copy()
subs = [("nofilter-taken", wk[wk.taken]),
        ("live-taken(4pass)", wk[(~wk.gate_rej) & (~wk.ms_rej) & (~wk.dt_rej) & (~wk.sweep_rej) & wk.taken]),
        ("all", wk)]
for name, sub in subs:
    print(f"[WK] {name}: {len(sub)}")
    for gname in ["стоп за уровнем", "фитиль наколол, стоп перед уровнем", "уровень не взят", "нет уровня"]:
        g = sub[sub.grp == gname]
        if len(g):
            print(f"   {gname}: {len(g)} / {round((g.outcome=='tp').mean()*100,1)}% / {round(g.q.mean(),3)}")

# sanity: wick_lo <= stop (LONG) / wick_hi >= stop (SHORT)?
lg = wk[wk.direction == "LONG"]
sh = wk[wk.direction == "SHORT"]
print("[WK] LONG wick_lo<=stop:", int((lg.wick_lo <= lg.stop + 1e-9).sum()), "of", len(lg))
print("[WK] SHORT wick_hi>=stop:", int((sh.wick_hi >= sh.stop - 1e-9).sum()), "of", len(sh))
# у группы "стоп за уровнем" фитиль дошёл до уровня?
a = wk[wk.grp == "стоп за уровнем"]
an = a[a.direction == "LONG"]
recon = (an.entry * (1 - an.lvl_pct / 100))
print("[WK] стоп-за-уровнем LONG: wick_lo<=lvl_near:", int((an.wick_lo <= recon + 1e-9).sum()), "of", len(an))

# ---- join with base 998
base_rows = []
for f in glob.glob(os.path.join(BASE_DIR, "*.pkl")):
    base_rows += pickle.load(open(f, "rb"))
bt = [r for r in base_rows if r.get("taken") and r.get("r") is not None]
print("\nbase taken:", len(bt))
wmap = {}
for rec in wk.itertuples():
    wmap[(rec.symbol, str(rec.scan), rec.direction)] = rec
join = []
for r in bt:
    rec = wmap.get((r["sym"], str(r["scan"]), r["direction"]))
    if rec is None:
        continue
    join.append({"grp": rec.grp, "lvl_type": rec.lvl_type, "lvl_pct": rec.lvl_pct,
                 "q_wk": float(rec.q), "r_base": float(r["r"]), "outcome": r["outcome"],
                 "year": str(r["scan"])[:4], "dir": r["direction"], "entry": r["entry"],
                 "sweep": r.get("htf_sweep_level")})
jd = pd.DataFrame(join)
print("[JOIN] matched:", len(jd), "of", len(bt))
for gname in ["стоп за уровнем", "фитиль наколол, стоп перед уровнем", "уровень не взят", "нет уровня"]:
    g = jd[jd.grp == gname]
    if len(g):
        print(f"   {gname}: n={len(g)} WR={round((g.outcome=='tp').mean()*100,1)}% "
              f"avgR_q={round(g.q_wk.mean(),3)} avgR_base={round(g.r_base.mean(),3)}")

print("\n[JOIN] D-таблица: стоп за уровнем по типу уровня")
g = jd[jd.grp == "стоп за уровнем"]
for typ, gg in g.groupby(g.lvl_type.fillna("нет")):
    print(f"   {typ}: n={len(gg)} WR={round((gg.outcome=='tp').mean()*100,1)}% "
          f"avgR_q={round(gg.q_wk.mean(),3)} avgR_base={round(gg.r_base.mean(),3)}")

sh_rows = g[g.lvl_type == "SWING_HIGH"]
print("\n[JOIN] SWING_HIGH(стоп за ур.) по годам:")
for y in ("2024", "2025", "2026"):
    gy = sh_rows[sh_rows.year == y]
    if len(gy):
        print(f"   {y}: n={len(gy)} avgR_q={round(gy.q_wk.mean(),3)} avgR_base={round(gy.r_base.mean(),3)}")
other_sh = jd[(jd.dir == "SHORT") & ~((jd.grp == "стоп за уровнем") & (jd.lvl_type == "SWING_HIGH"))]
print("[JOIN] остальные шорты: n", len(other_sh), "avgR_base", round(other_sh.r_base.mean(), 3))

# ---- source-level overlap: lvl near == htf_sweep_level?
ov = jd.dropna(subset=["lvl_pct", "sweep"]).copy()
near = np.where(ov.dir == "LONG", ov.entry * (1 - ov.lvl_pct / 100), ov.entry * (1 + ov.lvl_pct / 100))
ov["near"] = near
ov["hit"] = np.abs(ov.near - ov.sweep) / ov.entry <= 0.0002
print("\n[JOIN] level==sweep_level (2bps):", int(ov.hit.sum()), "of", len(ov),
      "by grp:", ov.groupby("grp").hit.mean().round(3).to_dict())

# ---- stop == trigger_extreme?
bad = tot = 0
mx = 0.0
for f in glob.glob(os.path.join(NF_DIR, "*.pkl")):
    for r in pickle.load(open(f, "rb")):
        d = abs(float(r["stop"]) - float(r["trigger_extreme"])) / float(r["entry"])
        tot += 1
        mx = max(mx, d)
        if d > 1e-9:
            bad += 1
print("\n[NF] stop==trigger_extreme: mismatches", bad, "of", tot, "max rel diff", mx)

# ---- medians stop: пусто vs близко (проверка resume-A)
tn = nf[(nf.taken == True) & nf.r.notna()].copy()
print("[NF] taken med sp %:", round(tn.sp.median() * 100, 3))
emp = tn[tn.nearest_opposing_R.isna()]
print("[NF] taken old-empty med sp %:", round(emp.sp.median() * 100, 3), "n", len(emp))
close = tn[tn.nearest_opposing_R.notna() & (tn.nearest_opposing_R < 0.5)]
print("[NF] taken close(<0.5R) med sp %:", round(close.sp.median() * 100, 3), "n", len(close))
withlv = tn[tn.nearest_opposing_R.notna()]
print("[NF] taken with-level med sp %:", round(withlv.sp.median() * 100, 3), "n", len(withlv))
for lo, hi, nm in [(0, 0.05, "<0.05R"), (0.05, 0.25, "0.05-0.25R"), (0.25, 1, "0.25-1R"), (1, 5, "1-5R")]:
    g = tn[(tn.nearest_opposing_R >= lo) & (tn.nearest_opposing_R < hi)]
    if len(g):
        print(f"[NF] taken {nm}: med sp % {round(g.sp.median()*100,3)} n {len(g)}")

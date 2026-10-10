"""Прогон tf8-потока с новым правилом (b9d3d3f): пересвип глубже снимает мелких
кандидатов по всем окнам. Считаем, сколько сделок правило убирает и сколько это стоит в ΣR.

Правило (эмуляция live-логики на потоке бэктеста):
 - кандидат = (направление, HTF-окно) внутри пары; живут кандидаты последних 2 окон (tf8);
 - кандидат глубже по триггер-экстремуму ИЛИ по уровню свипа (строго, без равенства);
 - если живой кандидат глубже входящего  -> сигнал НЕ берём (сделки нет);
 - если входящий глубже живого          -> старый кандидат снимается, а его лимитка отменяется:
     * если по старому кандидату сделка УЖЕ вошла (entry_bar <= scan_bar нового сигнала) —
       позиция не трогается, сделка остаётся;
     * иначе сделка не состоится -> вычитаем из потока.
"""
import glob
import pickle
from collections import defaultdict

import pandas as pd

PAT = "D:/PYTHON/CISDBOT/RUNS/filters_off_full/*tf8*.pkl"
EPS = 1e-8


def deeper(direction: str, a: float, b: float) -> bool:
    return a < b - EPS if direction == "LONG" else a > b + EPS


sigs, trades = [], {}
for f in sorted(glob.glob(PAT)):
    c = pickle.load(open(f, "rb"))
    sym = c.get("symbol")
    for s in c.get("signals") or []:
        sigs.append({
            "sym": sym, "dir": s.get("direction"), "htf": str(s.get("htf_time")),
            "sweep": float(s.get("htf_sweep_level") or 0),
            "ext": float(s.get("trigger_extreme") or 0),
            "scan": s.get("scan_bar"), "trig_time": str(s.get("trigger_bar_time")),
            "hash": str(s.get("hash")),
        })
    for t in c.get("trades") or []:
        trades[str(t.get("hash"))] = {
            "r": float(t.get("r_net") or 0), "outcome": t.get("outcome"),
            "entry_bar": t.get("entry_bar"), "created_bar": t.get("created_bar"),
        }

df = pd.DataFrame(sigs)
df["htf_ts"] = pd.to_datetime(df["htf"], errors="coerce")
df = df.sort_values(["sym", "scan", "htf_ts"]).reset_index(drop=True)
print(f"сигналов: {len(df)} | сделок: {len(trades)} | ΣR потока: {sum(t['r'] for t in trades.values()):+.1f}")

removed, kept_entered, suppressed = [], 0, 0
total_removed_r = 0.0
for sym, g in df.groupby("sym"):
    cands = {}          # (dir, htf) -> dict
    win_order = []      # порядок окон по времени появления
    for r in g.itertuples():
        key = (r.dir, r.htf)
        if r.htf not in win_order:
            win_order.append(r.htf)
        keep_windows = set(win_order[-2:])          # n_htf_keep = 2 окна
        cands = {k: v for k, v in cands.items() if k[1] in keep_windows}

        sibs = {k: v for k, v in cands.items() if k[0] == r.dir and k != key}
        beats_in = {k: (deeper(r.dir, r.ext, v["ext"]) or deeper(r.dir, r.sweep, v["sweep"]))
                    for k, v in sibs.items()}
        beats_sib = {k: (deeper(r.dir, v["ext"], r.ext) or deeper(r.dir, v["sweep"], r.sweep))
                     for k, v in sibs.items()}

        if any(beats_sib[k] and not beats_in[k] for k in sibs):
            suppressed += 1
            t = trades.get(r.hash)
            if t:
                removed.append(dict(sym=sym, dir=r.dir, htf=r.htf, sweep=r.sweep, ext=r.ext,
                                    why="не берём (живой глубже)", r=t["r"]))
                total_removed_r += t["r"]
            continue

        for k, v in sibs.items():
            if beats_in[k] and not beats_sib[k]:
                t = trades.get(v["hash"])
                if t and t["entry_bar"] is not None and r.scan is not None and \
                        float(t["entry_bar"]) <= float(r.scan):
                    kept_entered += 1               # уже в позиции -> не трогаем
                elif t:
                    removed.append(dict(sym=sym, dir=r.dir, htf=v["htf"], sweep=v["sweep"],
                                        ext=v["ext"], why=f"снят пересвипом {v['sweep']:.5f}→{r.sweep:.5f}",
                                        r=t["r"]))
                    total_removed_r += t["r"]
                cands.pop(k, None)

        cur = cands.get(key)
        if cur is None:
            cands[key] = dict(sweep=r.sweep, ext=r.ext, hash=r.hash, htf=r.htf)
        else:
            if deeper(r.dir, r.ext, cur["ext"]) or deeper(r.dir, r.sweep, cur["sweep"]):
                t = trades.get(cur["hash"])
                if t and t["entry_bar"] is not None and r.scan is not None and \
                        float(t["entry_bar"]) <= float(r.scan):
                    kept_entered += 1
                elif t:
                    removed.append(dict(sym=sym, dir=r.dir, htf=cur["htf"],
                                        sweep=cur["sweep"], ext=cur["ext"],
                                        why="обновление в своём окне (лимитка снята)", r=t["r"]))
                    total_removed_r += t["r"]
                cands[key] = dict(sweep=r.sweep, ext=r.ext, hash=r.hash, htf=r.htf)

print()
print("=== ЭФФЕКТ ПРАВИЛА НА ПОТОК ===")
print(f"сигналов «не берём» (живой глубже): {suppressed}")
print(f"сделок снято правилом: {len(removed)} | их ΣR: {total_removed_r:+.1f}")
print(f"сделок сохранено, т.к. уже были в позиции (не трогаем): {kept_entered}")
print(f"ΣR потока после правила: {sum(t['r'] for t in trades.values()) - total_removed_r:+.1f} "
      f"(было {sum(t['r'] for t in trades.values()):+.1f})")

if removed:
    rd = pd.DataFrame(removed)
    print()
    print("--- снятые: по годам (сделок / ΣR) ---")
    rd["year"] = pd.to_datetime(rd["htf"], errors="coerce").dt.year
    for y, gg in rd.groupby("year"):
        print(f"  {int(y)}: {len(gg):4d} | {gg['r'].sum():+7.1f}")
    print("--- по парам (сделок / ΣR) ---")
    for s, gg in rd.groupby("sym"):
        print(f"  {s:5s}: {len(gg):4d} | {gg['r'].sum():+7.1f}")
    print(f"--- ср. R снятых: {rd['r'].mean():+.3f} | WR {100 * (rd['r'] > 0).mean():.1f}% "
          f"| плюс {int((rd['r'] > 0).sum())} / минус {int((rd['r'] < 0).sum())} ---")
    print("--- примеры ---")
    for x in removed[:8]:
        print(f"  {x['sym']} {x['dir']} {x['htf'][5:16]} sweep={x['sweep']} ext={x['ext']} R={x['r']:+.2f} — {x['why']}")

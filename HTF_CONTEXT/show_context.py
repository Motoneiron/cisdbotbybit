# -*- coding: utf-8 -*-
"""HTF Context Engine — просмотр контекста сигнала «глазами» (ТЗ: JSONL должен читаться человеком).

Примеры:
    python -m HTF_CONTEXT.show_context --symbol ADA --scan "2024-06-03 19:15"
    python -m HTF_CONTEXT.show_context --symbol SOL --idx 5          # 5-й сигнал SOL
    python -m HTF_CONTEXT.show_context --symbol KAS --scan 2024-04    # первый за апрель 2024
"""
from __future__ import annotations

import argparse
import json
import os
import sys

DEFAULT_JSONL = r"D:\PYTHON\cisdbotbybit\RUNS\cache\htf_context.jsonl"


def load_lines(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(x) for x in f if x.strip()]


def fmt_path_item(o: dict) -> str:
    if "lo" in o:
        zone = f"[{o['lo']},{o['hi']}]"
        if "rem_lo" in o and (o["rem_lo"] != o["lo"] or o["rem_hi"] != o["hi"]):
            zone += f" остаток[{o['rem_lo']},{o['rem_hi']}]"
        extra = f" fill={o.get('fill_pct')}"
        return f"{o['distance_R']:6.3f}R {o['tf']:>2} {o['type']:<10} {o['state']:<17}{zone}{extra}"
    return f"{o['distance_R']:6.3f}R {o['tf']:>2} {o['type']:<10} {o['state']:<17} level={o.get('level')}"


def fmt_map_list(items: list[dict]) -> str:
    if not items:
        return "-"
    parts = []
    for it in items:
        if "level" in it:
            parts.append(f"{it['signed_distance_pct']:+.2f}% {it['level']} ({it['state']})")
        else:
            parts.append(f"{it['signed_distance_pct']:+.2f}% [{it['lo']},{it['hi']}] "
                         f"({it['state']}, fill={it.get('fill_pct')}, {it['side']})")
    return "; ".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jsonl", default=DEFAULT_JSONL)
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--scan", default=None, help="префикс метки времени счёта (например 2024-06-03 19:15)")
    ap.add_argument("--idx", type=int, default=None, help="номер сигнала символа (0-based)")
    args = ap.parse_args()

    if not os.path.exists(args.jsonl):
        print(f"нет файла {args.jsonl} — сначала запусти research_htf_context")
        return 1
    lines = [L for L in load_lines(args.jsonl) if L.get("symbol") == args.symbol]
    if args.idx is not None:
        cand = lines[args.idx: args.idx + 1]
    elif args.scan:
        cand = [L for L in lines if str(L.get("scan", "")).startswith(args.scan)]
    else:
        cand = lines[:1]
    if not cand:
        print("не найдено")
        return 1
    for L in cand:
        c = L["context"]; s = c["summary"]; sig = c["signal"]
        print("=" * 100)
        take = "taken" if L.get("taken") else f"skip:{L.get('skip_reason')}"
        print(f"{L['symbol']} {L['scan']} {L['direction']}  [{take}] "
              f"outcome={L.get('outcome')} r={L.get('r')} sp={round(float(L['sp'])*100,3)}%")
        print(f"  entry={sig['entry']} stop={sig['stop']} tp={sig['target']} px={sig['px']} "
              f"sweep={sig['htf_sweep_level']} (excluded: {len(c.get('excluded_sources') or [])})")
        print(f"  summary: nearest={s['nearest_opposing_obstacle_R']}R ({s['nearest_opposing_obstacle_pct']}%) "
              f"internal={s['nearest_internal_liquidity_R']}R external={s['nearest_external_liquidity_R']}R "
              f"tp_blocked={s['tp_blocked']} | <1R:{s['obstacle_count_under_1R']} <2R:{s['obstacle_count_under_2R']}")
        for tf in ("4H", "1D", "1W"):
            b = c["htf"][tf]
            print(f"  {tf}: range [{b['range_low']},{b['range_high']}] pos={b['range_position']} "
                  f"{b['premium_discount']} | obt={b['nearest_obstacle_R']} fvg={b['nearest_fvg_R']} swing={b['nearest_swing_R']}")
            print(f"      fvg_above: {fmt_map_list(b['fvg_above'])}")
            print(f"      fvg_below: {fmt_map_list(b['fvg_below'])}")
        print("  reference: " + "; ".join(
            f"{k}={v['level']}({v['side']},{v['distance_R']}R)" for k, v in c["reference"].items() if v))
        print("  path:")
        for o in c["path"]:
            print("    " + fmt_path_item(o))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

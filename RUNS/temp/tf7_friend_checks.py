"""Проверки по замечаниям к tf7-канону, без нового прогона детекта.

Берёт готовые сделки ABL_MSS_MAIN (честный якорь, A+V+D, MSS 5m):
  1. Год 2026 отдельно (это H1, данные до 23.06).
  2. Кластер пар: одни и те же дни и одно 4H-окно.
  3. Фандинг на момент 4H-окна сигнала (гипотеза: экстремум в сторону толпы).
  4. Режим волатильности: перцентиль ATR за вчера среди 20 прошлых суток.
  5. Прокси ликвидности у уровня: оборот USDT в ±0,1% внутри 4H-окна.
  6. Что будет с R, если мейкер на входе или на TP не исполнился (только комиссия).

Запуск: python tf7_friend_checks.py
"""
from __future__ import annotations

import glob
import pickle
import sys
from bisect import bisect_right

import numpy as np
import pandas as pd

sys.path.insert(0, r"D:/PYTHON")
sys.path.insert(0, r"D:/PYTHON/CISDBOT")

from backtest.data import resolve_csv_path  # noqa: E402

ABL = r"D:/PYTHON/cisdbotbybit/RUNS/temp/tf7_abl"
FUND = r"D:/PYTHON/cisdbotbybit/RUNS/temp/funding_bybit.pkl"
OUT = r"D:/PYTHON/cisdbotbybit/RUNS/temp/TF7_FRIEND_CHECKS_2026-09-23.md"
CORE = ["SOL", "LINK", "ADA", "KAS", "DOGE", "LTC"]


def fee_r(entry_maker: bool, exit_maker: bool, sp: float, maker: float, taker: float) -> float:
    if not sp or sp <= 0:
        return 0.0
    e = maker if entry_maker else taker
    x = maker if exit_maker else taker
    return (e + x) / sp


def tstat(x) -> tuple[float, int]:
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    n = int(x.size)
    if n < 3:
        return float("nan"), n
    s = float(x.std(ddof=1))
    if s == 0:
        return float("nan"), n
    return float(x.mean() / (s / np.sqrt(n))), n


def fmt(x, nd=3) -> str:
    if x is None or not np.isfinite(x):
        return "—"
    return f"{x:+.{nd}f}".replace(".", ",")


def fmtu(x, nd=2) -> str:
    if x is None or not np.isfinite(x):
        return "—"
    return f"{x:.{nd}f}".replace(".", ",")


def load_canon() -> pd.DataFrame:
    rows = []
    for f in glob.glob(ABL + "/ABL_MSS_MAIN_*.pkl"):
        rows.extend(pickle.load(open(f, "rb")))
    d = pd.DataFrame(rows)
    d["sp"] = pd.to_numeric(d["sp"], errors="coerce")
    d["r_mexc"] = pd.to_numeric(d["r_net_mexc"], errors="coerce")
    mexc_fee = [
        fee_r(True, o == "tp", s, 0.0006, 0.0008)
        for o, s in zip(d.outcome, d.sp)
    ]
    byb_fee = [
        fee_r(True, o == "tp", s, 0.00036, 0.0010)
        for o, s in zip(d.outcome, d.sp)
    ]
    d["fee_mexc"] = mexc_fee
    d["fee_byb"] = byb_fee
    d["gross"] = d["r_mexc"] + d["fee_mexc"]
    d["r_byb"] = d["gross"] - d["fee_byb"]
    d["htf_ts"] = pd.to_datetime(d["htf_time"], errors="coerce")
    d["day"] = d["htf_ts"].dt.floor("D")
    d["week"] = d["htf_ts"].dt.to_period("W-SUN").dt.start_time
    d["month"] = d["htf_ts"].dt.month
    return d


def line_block(title: str, part: pd.DataFrame, col: str) -> str:
    if len(part) == 0:
        return f"{title}: нет сделок"
    t, n = tstat(part[col])
    return (
        f"{title}: n={n}  avg={fmt(part[col].mean())}  "
        f"сумма={fmt(part[col].sum(), 1)}  t={fmt(t, 2)}"
    )


def section_years(d: pd.DataFrame) -> list[str]:
    lines = ["## 1. Годы, включая H1 2026", ""]
    lines.append("2026 в прогоне — с 1 января по 23 июня, это и есть первое полугодие.")
    lines.append("")
    lines.append("| срез | год | n | MEXC avg R | Bybit avg R | t Bybit |")
    lines.append("|---|---|---:|---:|---:|---:|")
    for name, mask0 in (
        ("все 10", pd.Series(True, index=d.index)),
        ("ядро-6", d.sym.isin(CORE)),
    ):
        for y in (2023, 2024, 2025, 2026):
            q = d[mask0 & (d.year.astype(int) == y)]
            t, n = tstat(q["r_byb"])
            lines.append(
                f"| {name} | {y}{' H1' if y == 2026 else ''} | {n} | {fmt(q.r_mexc.mean())} | "
                f"{fmt(q.r_byb.mean())} | {fmt(t, 2)} |"
            )
        q = d[mask0 & (d.year.astype(int) >= 2024)]
        t, n = tstat(q["r_byb"])
        lines.append(
            f"| {name} | 2024–26 | {n} | {fmt(q.r_mexc.mean())} | {fmt(q.r_byb.mean())} | {fmt(t, 2)} |"
        )
    lines.append("")
    q = d[(d.year.astype(int) == 2026) & d.sym.isin(CORE)].copy()
    lines.append("Ядро-6, 2026 по кварталам (внутри того же H1):")
    lines.append("")
    for label, m in (("Q1", q.month <= 3), ("Q2 до 23.06", q.month >= 4)):
        part = q[m]
        lines.append("- " + line_block(label + " Bybit", part, "r_byb"))
        lines.append("  " + line_block(label + " MEXC", part, "r_mexc"))
    lines.append("")
    return lines


def section_cluster(d: pd.DataFrame) -> list[str]:
    lines = ["## 2. Кластер пар: одни дни и одно 4H-окно", ""]
    lines.append(
        "Время сделки — открытие 4H-окна сигнала (htf_time), не штамп филла. "
        "Так совпадение не зависит от того, как 1m-филл лёг на 5m-индекс."
    )
    lines.append("")
    for label, mask, y0 in (
        ("ядро-6, 2024–26", d.sym.isin(CORE) & (d.year.astype(int) >= 2024), 2024),
        ("ядро-6, все годы", d.sym.isin(CORE), 2020),
        ("все 10, 2024–26", d.year.astype(int) >= 2024, 2024),
    ):
        q = d[mask].copy()
        lines.append(f"### {label}")
        lines.append("")
        lines.append("- " + line_block("сделки, Bybit", q, "r_byb"))
        daily = q.groupby("day")["r_byb"].sum()
        weekly = q.groupby("week")["r_byb"].sum()
        h4 = q.groupby("htf_ts")["r_byb"].sum()
        td, nd = tstat(daily)
        tw, nw = tstat(weekly)
        th, nh = tstat(h4)
        lines.append(
            f"- дни (сумма R пар за сутки): n={nd}  avg дня={fmt(daily.mean())}  t={fmt(td, 2)}"
        )
        lines.append(
            f"- недели: n={nw}  avg недели={fmt(weekly.mean())}  t={fmt(tw, 2)}"
        )
        lines.append(
            f"- 4H-окна (сумма R всех пар в одном htf_time): n={nh}  avg окна={fmt(h4.mean())}  t={fmt(th, 2)}"
        )
        # сколько пар делят окно
        per = q.groupby(["htf_ts", "sym"]).size().reset_index(name="k")
        n_pairs_win = per.groupby("htf_ts").size()
        share_shared = float((n_pairs_win.reindex(q["htf_ts"]).to_numpy() >= 2).mean())
        lines.append(
            f"- доля сделок, у которых в том же 4H-окне есть ещё хотя бы одна пара: {share_shared*100:.0f}%"
        )
        vc = n_pairs_win.value_counts().sort_index()
        bits = ", ".join(f"{int(k)} пар: {int(v)} окон" for k, v in vc.items())
        lines.append(f"- окон по числу пар: {bits}")

        # знак дневного R
        day_pair = q.groupby(["day", "sym"])["r_byb"].sum().unstack()
        active = day_pair.notna()
        n_active = active.sum(axis=1)
        signs = np.sign(day_pair)
        same = []
        for kmin in (2, 3, 4):
            rows = n_active >= kmin
            if rows.sum() == 0:
                continue
            sub_s = signs[rows]
            sub_a = active[rows]
            agree = []
            for i in range(len(sub_s)):
                s = sub_s.iloc[i][sub_a.iloc[i]].to_numpy()
                s = s[s != 0]
                if len(s) < 2:
                    continue
                agree.append(float(np.all(s == s[0])))
            if agree:
                same.append(
                    f">={kmin} пар в день: {len(agree)} дней, все одного знака {np.mean(agree)*100:.0f}%"
                )
        if same:
            lines.append("- совпадение знака дневного R: " + "; ".join(same))

        # средняя попарная корреляция дневных R (только дни, где обе торговали)
        cols = [c for c in CORE if c in day_pair.columns] if "ядро" in label else list(day_pair.columns)
        rhos = []
        for i, a in enumerate(cols):
            for b in cols[i + 1 :]:
                pair = day_pair[[a, b]].dropna()
                if len(pair) < 30:
                    continue
                rhos.append(float(pair[a].corr(pair[b])))
        if rhos:
            rho = float(np.mean(rhos))
            m = len(cols)
            n_eff = m / (1 + (m - 1) * rho) if rho > -1 else float("nan")
            lines.append(
                f"- средняя корреляция дневного R между парами (дни, когда обе в сделке): {fmtu(rho, 2)}. "
                f"Эффективных ставок из {m}: {fmtu(n_eff, 2)}."
            )

        # одно направление в одном 4H
        g = q.groupby(["htf_ts", "direction"])
        multi = []
        for _, part in g:
            if part["sym"].nunique() < 2:
                continue
            multi.append(part)
        if multi:
            outcomes = []
            rs = []
            for part in multi:
                dec = part[part.outcome.isin(["tp", "sl"])]
                if len(dec) >= 2:
                    outcomes.append(dec.outcome.nunique() == 1)
                rs.append(part.r_byb.mean())
            lines.append(
                f"- одно направление, одно 4H, ≥2 пар: {len(multi)} кластеров. "
                f"Среди тех, где исход tp/sl: все одинаковые в {np.mean(outcomes)*100:.0f}% случаев. "
                f"Средний R кластера (одна ставка = среднее пар) {fmt(np.mean(rs))}."
            )
            tclus, _ = tstat(rs)
            lines.append(
                f"- если каждый такой кластер считать одной ставкой, а одиночные сделки оставить как есть: "
                f"см. сжатую выборку ниже."
            )
            # compressed sample
            alone_r = []
            cluster_r = []
            for (ht, direction), part in g:
                if part["sym"].nunique() < 2:
                    alone_r.extend(part.r_byb.tolist())
                else:
                    cluster_r.append(float(part.r_byb.mean()))
            compressed = np.array(alone_r + cluster_r, dtype=float)
            tc, nc = tstat(compressed)
            lines.append(
                f"- сжатая выборка Bybit: n={nc} (было {len(q)})  avg={fmt(compressed.mean())}  t={fmt(tc, 2)}"
            )
        lines.append("")
    return lines


def load_funding() -> dict:
    rows = pickle.load(open(FUND, "rb"))
    by = {}
    for sym, ts, rate in rows:
        by.setdefault(sym, []).append((int(ts), float(rate)))
    for sym in by:
        by[sym].sort()
    return by


def rate_asof(series, ts_ms: int):
    if not series:
        return None
    times = [t for t, _ in series]
    i = bisect_right(times, ts_ms) - 1
    if i < 0:
        return None
    # не брать ставку старше 16 часов — иначе дыра в истории
    if ts_ms - series[i][0] > 16 * 3600 * 1000:
        return None
    return series[i][1]


def section_funding(d: pd.DataFrame) -> list[str]:
    lines = ["## 3. Фандинг на момент сигнала", ""]
    lines.append(
        "Ставка — последний фандинг Bybit на открытие 4H-окна или раньше (не старше 16 часов). "
        "Выравнивание: для SHORT плюс, если фандинг положительный (лонги платят); "
        "для LONG плюс, если фандинг отрицательный (шорты платят). "
        "Гипотеза заранее: крайний положительный бакет лучше среднего, потому что толпа сидит против отката."
    )
    lines.append("")
    fund = load_funding()
    q = d[d.sym.isin(CORE)].copy()
    rates = []
    for sym, ts in zip(q.sym, q.htf_ts):
        if pd.isna(ts):
            rates.append(np.nan)
            continue
        ms = int(pd.Timestamp(ts).timestamp() * 1000)
        r = rate_asof(fund.get(sym), ms)
        rates.append(np.nan if r is None else r)
    q["fund"] = pd.to_numeric(rates, errors="coerce")
    q["align"] = np.where(q.direction.to_numpy() == "SHORT", q.fund, -q.fund)
    q["align"] = pd.to_numeric(q["align"], errors="coerce")
    known = q[np.isfinite(q["align"].to_numpy())]
    lines.append(
        f"Ядро-6, фандинг найден у {len(known)} из {len(q)} сделок "
        f"({100*len(known)/max(len(q),1):.0f}%)."
    )
    lines.append("")

    def bucket_table(part: pd.DataFrame, edges: np.ndarray, title: str) -> list[str]:
        out = [f"### {title}", ""]
        out.append("| бакет align | n | MEXC | Bybit | t Bybit |")
        out.append("|---|---:|---:|---:|---:|")
        cats = pd.cut(part["align"], bins=edges, include_lowest=True)
        for lab in cats.cat.categories:
            g = part[cats == lab]
            t, n = tstat(g["r_byb"])
            out.append(
                f"| {lab} | {n} | {fmt(g.r_mexc.mean()) if n else '—'} | "
                f"{fmt(g.r_byb.mean()) if n else '—'} | {fmt(t, 2)} |"
            )
        out.append("")
        return out

    ins = known[known.year.astype(int) < 2024]
    oos = known[known.year.astype(int) >= 2024]
    if len(ins) >= 50:
        _, edges = pd.qcut(ins["align"], 5, retbins=True, duplicates="drop")
        edges = np.asarray(edges, dtype=float)
        edges[0] = -np.inf
        edges[-1] = np.inf
        lines.append(
            "Границы бакетов заморожены на годах до 2024. "
            "Ставки фандинга дискретные, одинаковые квантили схлопнуты. "
            "2024–26 режется этими же границами, без подгонки."
        )
        lines.append("")
        lines.extend(bucket_table(ins, edges, "До 2024, те же границы"))
        lines.extend(bucket_table(oos, edges, "2024–26, границы с до-2024"))
        thr = float(ins["align"].quantile(0.8))
        hi = oos[oos["align"] >= thr]
        rest = oos[oos["align"] < thr]
        lines.append(
            "Верхние 20% по порогу до 2024: align не ниже "
            + f"{thr * 100:.4f}%.".replace(".", ",")
        )
        lines.append(
            "- " + line_block("2024–26 верхний бакет Bybit", hi, "r_byb")
        )
        lines.append("- " + line_block("2024–26 остальные Bybit", rest, "r_byb"))
        lines.append("- " + line_block("2024–26 верхний MEXC", hi, "r_mexc"))
        lines.append("- " + line_block("2024–26 остальные MEXC", rest, "r_mexc"))
        lines.append("")
    else:
        lines.append("До 2024 мало сделок с фандингом, квинтили только описательные на 2024–26.")
        lines.append("")
    return lines


def _read_1m(sym: str) -> pd.DataFrame | None:
    try:
        path = resolve_csv_path(sym, "1m")
    except Exception:
        return None
    if not path.exists():
        return None
    header = pd.read_csv(path, nrows=0).columns
    quote_col = "quote_volume" if "quote_volume" in header else "quote_asset_volume"
    usecols = ["open_time", "high", "low", "close", "volume"]
    if quote_col in header:
        usecols.append(quote_col)
    df = pd.read_csv(path, usecols=usecols)
    if quote_col in df.columns:
        df = df.rename(columns={quote_col: "quote_volume"})
    else:
        df["quote_volume"] = df["volume"] * df["close"]
    df["dt"] = pd.to_datetime(df["open_time"], unit="ms")
    return df.set_index("dt").sort_index()


def _atr_pct_by_day(sym: str):
    df = _read_1m(sym)
    if df is None:
        return None
    ohlc = df.resample("5min").agg({"high": "max", "low": "min", "close": "last"})
    ohlc = ohlc.dropna(subset=["close"])
    prev = ohlc["close"].shift()
    tr = pd.concat(
        [
            ohlc["high"] - ohlc["low"],
            (ohlc["high"] - prev).abs(),
            (ohlc["low"] - prev).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = tr.rolling(14).mean()
    atr_pct = atr / ohlc["close"]
    daily = atr_pct.resample("1D").median().dropna()
    vals = daily.to_numpy()
    idx = daily.index
    out = np.full(len(vals), np.nan)
    for i in range(20, len(vals)):
        window = vals[i - 20 : i]
        v = vals[i - 1]
        if not np.isfinite(v) or not np.isfinite(window).all():
            continue
        out[i] = float((window <= v).mean())
    return pd.Series(out, index=idx.floor("D")), df


def section_vol_and_liq(d: pd.DataFrame) -> list[str]:
    lines = ["## 4. Режим волатильности", ""]
    lines.append(
        "Для каждого дня: медианный ATR(14)/цена на 5m за вчера, "
        "его место среди 20 предыдущих суток (0 = тише обычного, 1 = шумнее). "
        "Считается только по прошлому, без дня сделки."
    )
    lines.append("")
    lines.append("| период | бакет | n | MEXC | Bybit | t Bybit |")
    lines.append("|---|---|---:|---:|---:|---:|")
    cache_px = {}
    parts = []
    for sym in CORE:
        got = _atr_pct_by_day(sym)
        if got is None:
            lines.append(f"нет 1m для {sym}")
            continue
        pct, raw = got
        cache_px[sym] = raw
        sub = d[(d.sym == sym)].copy()
        sub["day"] = sub["htf_ts"].dt.floor("D")
        sub["vol_pct"] = sub["day"].map(pct)
        parts.append(sub)
    if not parts:
        lines.append("волатильность не посчиталась")
        return lines
    allp = pd.concat(parts, ignore_index=True)
    labels = [(0.0, 0.2, "0–20 тихо"), (0.2, 0.4, "20–40"), (0.4, 0.6, "40–60"),
              (0.6, 0.8, "60–80"), (0.8, 1.01, "80–100 шумно")]
    for period, mask in (
        ("до 2024", allp.year.astype(int) < 2024),
        ("2024–26", allp.year.astype(int) >= 2024),
    ):
        base = allp[mask & np.isfinite(allp.vol_pct)]
        for lo, hi, name in labels:
            g = base[(base.vol_pct >= lo) & (base.vol_pct < hi)]
            t, n = tstat(g["r_byb"])
            lines.append(
                f"| {period} | {name} | {n} | {fmt(g.r_mexc.mean()) if n else '—'} | "
                f"{fmt(g.r_byb.mean()) if n else '—'} | {fmt(t, 2)} |"
            )
    lines.append("")
    known = allp[np.isfinite(allp.vol_pct)]
    lines.append(f"Перцентиль есть у {len(known)} из {len(allp)} сделок ядра.")
    lines.append("")

    lines.append("## 5. Оборот у уровня (прокси вместо стакана)")
    lines.append("")
    lines.append(
        "L2-истории нет. Прокси: сумма quote_volume тех 1m-свечей внутри 4H-окна сигнала, "
        "чей диапазон пересёк цену входа ±0,1%. Это не вероятность филла в очереди, "
        "а сколько USDT реально напечаталось рядом с уровнем. "
        "Бэктест и так считает филл идеальным, поэтому R по «тонким» уровням — про цену, не про отказ лимитки."
    )
    lines.append("")
    aligned = []
    # recompute aligned properly
    for sym, raw in cache_px.items():
        sub = d[d.sym == sym].copy()
        idx = raw.index
        highs = raw["high"].to_numpy()
        lows = raw["low"].to_numpy()
        quote = raw["quote_volume"].to_numpy()
        vols = []
        for px, htf in zip(sub.entry_px, sub.htf_ts):
            if pd.isna(htf) or not px or px <= 0:
                vols.append(np.nan)
                continue
            t0 = pd.Timestamp(htf)
            t1 = t0 + pd.Timedelta(hours=4)
            lo = int(idx.searchsorted(t0, side="left"))
            hi = int(idx.searchsorted(t1, side="left"))
            if hi <= lo:
                vols.append(0.0)
                continue
            band_lo = float(px) * 0.999
            band_hi = float(px) * 1.001
            m = (lows[lo:hi] <= band_hi) & (highs[lo:hi] >= band_lo)
            vols.append(float(quote[lo:hi][m].sum()))
        sub["liq_usdt"] = vols
        aligned.append(sub)
    liq = pd.concat(aligned, ignore_index=True)
    finite = liq[np.isfinite(liq.liq_usdt)]
    zero = float((finite.liq_usdt <= 0).mean()) if len(finite) else float("nan")
    lines.append(
        f"Ядро, все годы: n={len(finite)}, доля окон с нулевым оборотом в ±0,1%: {zero*100:.1f}%."
    )
    if len(finite):
        for p in (10, 25, 50, 75, 90):
            v = float(np.percentile(finite.liq_usdt, p))
            lines.append(f"- p{p}: {v:,.0f} USDT".replace(",", " "))
    lines.append("")
    lines.append("| период | бакет оборота | n | MEXC | Bybit |")
    lines.append("|---|---|---:|---:|---:|")
    for period, mask in (
        ("до 2024", finite.year.astype(int) < 2024),
        ("2024–26", finite.year.astype(int) >= 2024),
    ):
        base = finite[mask]
        if len(base) < 20:
            continue
        # терцили внутри периода, описательно
        e1, e2 = np.quantile(base.liq_usdt, [1 / 3, 2 / 3])
        for name, g in (
            ("тонкий", base[base.liq_usdt <= e1]),
            ("средний", base[(base.liq_usdt > e1) & (base.liq_usdt <= e2)]),
            ("плотный", base[base.liq_usdt > e2]),
        ):
            lines.append(
                f"| {period} | {name} | {len(g)} | {fmt(g.r_mexc.mean())} | {fmt(g.r_byb.mean())} |"
            )
    lines.append("")
    return lines


def section_maker(d: pd.DataFrame) -> list[str]:
    lines = ["## 6. Если мейкер не исполнился", ""]
    lines.append(
        "Грубый R в сделке уже посчитан движком на комиссиях MEXC. "
        "Дальше меняется только комиссия Bybit: вход и TP по умолчанию мейкер 0,036%, "
        "стоп и таймаут — тейкер 0,10%. Проскальзывание цены сюда не входит, "
        "поэтому живой ущерб от тейкер-входа будет больше, чем в таблице."
    )
    lines.append("")
    lines.append("| срез | сценарий | avg R | t |")
    lines.append("|---|---|---:|---:|")

    def scenario(part, entry_taker_frac: float, tp_taker_frac: float) -> tuple[float, float]:
        # линейно по доле сделок, где конец становится тейкером
        sp = part.sp.to_numpy()
        outcome = part.outcome.to_numpy()
        gross = part.gross.to_numpy()
        base_entry = 0.00036
        taker = 0.0010
        maker = 0.00036
        entry_fee = base_entry + entry_taker_frac * (taker - maker)
        exit_fee = np.where(
            outcome == "tp",
            maker + tp_taker_frac * (taker - maker),
            taker,
        )
        r = gross - (entry_fee + exit_fee) / np.where(sp > 0, sp, np.nan)
        return r

    for name, mask in (
        ("все 10, 2024–26", d.year.astype(int) >= 2024),
        ("ядро-6, 2024–26", d.sym.isin(CORE) & (d.year.astype(int) >= 2024)),
        ("ядро-6, MEXC-ставки как есть", None),
    ):
        if name.startswith("ядро-6, MEXC"):
            part = d[d.sym.isin(CORE) & (d.year.astype(int) >= 2024)]
            t, _ = tstat(part.r_mexc)
            lines.append(f"| {name} | движок MEXC | {fmt(part.r_mexc.mean())} | {fmt(t, 2)} |")
            continue
        part = d[mask]
        for title, ef, tf_ in (
            ("оба мейкера (канон)", 0.0, 0.0),
            ("вход тейкер в 25% сделок", 0.25, 0.0),
            ("вход тейкер в 50%", 0.50, 0.0),
            ("вход всегда тейкер", 1.0, 0.0),
            ("TP тейкер в 50% (вход мейкер)", 0.0, 0.50),
            ("вход и TP всегда тейкер", 1.0, 1.0),
        ):
            r = scenario(part, ef, tf_)
            t, _ = tstat(r)
            lines.append(f"| {name} | {title} | {fmt(np.nanmean(r))} | {fmt(t, 2)} |")
    lines.append("")
    return lines


def main() -> None:
    d = load_canon()
    print(f"canon trades {len(d)}", flush=True)
    chunks = [
        "# Проверки tf7-канона по замечаниям (23.09.2026)",
        "",
        "Источник сделок: `ABL_MSS_MAIN` (MSS на 5m, фильтры A+V+D, окно 10 мин / 12 ч, честный якорь). "
        "Новый детект здесь не запускался. Пороги A/V/D — отдельным прогоном.",
        "",
    ]
    chunks += section_years(d)
    print("years done", flush=True)
    chunks += section_cluster(d)
    print("cluster done", flush=True)
    chunks += section_funding(d)
    print("funding done", flush=True)
    chunks += section_vol_and_liq(d)
    print("vol/liq done", flush=True)
    chunks += section_maker(d)
    text = "\n".join(chunks) + "\n"
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(text)
    print(text)
    print("WROTE", OUT, flush=True)


if __name__ == "__main__":
    main()

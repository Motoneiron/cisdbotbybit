# ЭСКИЗ ПАТЧА: Эллиотт-гейт «гонка» (SKIP) в cisdbot.py

**База:** коммит `6a35a09` (14.09.2026, «Add shadow CVD order-flow log with /cvd toggle»), файл `D:\PYTHON\cisdbotbybit\cisdbot.py` (14 559 строк). Все номера строк — по этой версии.
**Стиль:** как у CVD (ЭТАП 1 = фичи в журнал/карточку без влияния; ЭТАП 2 = применение SKIP).
**Что даёт (по бэктесту, поток lv0, 2020-26):** режем ~7.5% сделок (у них WR 49.3%, ΣR −222); поток +5429 → +5651.6R, WR 70.3 → 72.1%. Минус в отрезаемом КАЖДЫЙ год. Порог не хрупкий (0.15/0.236 → +232/+222R).

> ⚠️ **ПАУЗА ЯКОРЯ (14.09, вечер):** эти числа — на `decision_at` (+26/60 мин после конфирма, ПОСЛЕ филла) — не лайв-якорь; пересчёт идёт (`_q_reanchor.py`). ЭТАП 1 (shadow, deploy12) — безопасен, остаётся; **ЭТАП 2 (SKIP) НЕ включать** до пересчёта и повторной проверки на лайв-якоре.

**Предикат «гонка»:** `(dir == zz_last_dir) & (zz_frac < 0.236)` — сигнал вдоль последней ноги ZigZag с мелким откатом.
**ZigZag:** HTF = tf7→4h, tf8→8h; порог θ=1.5×ATR14(HTF); каузально (пивот известен только с бара подтверждения).

---

## Правка 1. Конфиг — после строки 171 (после `CVD_TIMEOUT_S`)

ДО:
```python
CVD_TIMEOUT_S    = 3.0
ACTIVE_SYMBOL_KEYS = (
```
ПОСЛЕ:
```python
CVD_TIMEOUT_S    = 3.0
# ==== Эллиотт-структура ZigZag HTF (ЭТАП 1: shadow-лог, скип выключен) ====
ELLIOTT_ENABLED    = True
ELLIOTT_APPLY_SKIP = False        # ЭТАП 2: True → SKIP «гонка»
ELLIOTT_FRAC       = 0.236        # порог отката «гонки»
ELLIOTT_THETA      = 1.5          # ATR-порог ZigZag
ACTIVE_SYMBOL_KEYS = (
```

## Правка 2. Две функции — вставить после строки 9386 (сразу за `_cvd_weight`, перед `create_pending_limit`)

```python
def _zigzag(htf: pd.DataFrame, atr: pd.Series, theta: float):
    """ZigZag по HTF: пивот подтверждается после отката >= theta*ATR.
    Порт БИТ-В-БИТ из _elliott_proxy_v1.py (каузальный).
    pivots: [(confirm_time, extreme_time, price, 'up'|'down'), ...]"""
    pivots = []
    idx = htf.index
    h = htf["high"].to_numpy(float)
    l = htf["low"].to_numpy(float)
    c = htf["close"].to_numpy(float)
    a = atr.to_numpy(float)
    n = len(htf)
    if n < 3:
        return pivots, None
    dirn = 1 if c[1] >= c[0] else -1
    ext = h[1] if dirn == 1 else l[1]
    ext_i = 1
    for i in range(2, n):
        if not np.isfinite(a[i]) or a[i] <= 0:
            continue
        if dirn == 1:
            if h[i] > ext:
                ext, ext_i = h[i], i
            elif (ext - l[i]) >= theta * a[i]:
                pivots.append((idx[i], idx[ext_i], ext, "up"))
                dirn, ext, ext_i = -1, l[i], i
        else:
            if l[i] < ext:
                ext, ext_i = l[i], i
            elif (h[i] - ext) >= theta * a[i]:
                pivots.append((idx[i], idx[ext_i], ext, "down"))
                dirn, ext, ext_i = 1, h[i], i
    return pivots, (dirn, ext, ext_i)


def _elliott_features(df: pd.DataFrame, tf_name: str, sig: dict) -> tuple[Optional[dict], str]:
    """Причинный Эллиотт-прокси на scan-моменте: ZigZag по HTF (tf7→4h, tf8→8h), θ=1.5 ATR.
    Каузально строже прототипа: пивоты — только по ПОЛНОСТЬЮ закрытым HTF-бакетам;
    глубина отката — по LTF-барам от пивота до scan (без «хвоста» текущего бакета).
    Возврат: ({zz_last_dir, zz_frac, verdict}, reason) либо (None, reason) — фильтр НЕ блокирует при None."""
    from backtest.sweep_atr_filter import compute_atr14
    try:
        scan_raw = sig.get("confirm_bar_time") or sig.get("timestamp")
        df_cut = df
        if scan_raw:
            ts = pd.Timestamp(scan_raw)
            if getattr(ts, "tzinfo", None) is not None:
                ts = ts.tz_convert("UTC").tz_localize(None) if ts.tzinfo else ts.tz_localize(None)
            df_cut = df.loc[:ts]
        if df_cut is None or len(df_cut) < 60:
            return None, "elliott: мало LTF-баров — фильтр не применён"
        rule = "4h" if tf_name == "tf7" else "8h"
        tfm = 5 if tf_name == "tf7" else 30
        htf = pd.DataFrame({
            "high":  df_cut["high"].resample(rule, label="left", closed="left").max(),
            "low":   df_cut["low"].resample(rule, label="left", closed="left").min(),
            "close": df_cut["close"].resample(rule, label="left", closed="left").last(),
        }).dropna()
        if len(htf) < 4:
            return None, "elliott: мало HTF-баров — фильтр не применён"
        scan_dt = pd.Timestamp(df_cut.index[-1]) + pd.Timedelta(minutes=tfm)
        htf_closed = htf.loc[htf.index + pd.Timedelta(rule) <= scan_dt]
        if len(htf_closed) < 3:
            return None, "elliott: нет закрытых HTF — фильтр не применён"
        atr = compute_atr14(htf_closed)
        pivots, _ = _zigzag(htf_closed, atr, ELLIOTT_THETA)
        if len(pivots) < 2:
            return None, "elliott: менее 2 пивотов — фильтр не применён"
        pB, pA = pivots[-1], pivots[-2]
        leg_len = abs(pB[2] - pA[2])
        if not (leg_len > 0):
            return None, "elliott: нулевой лег — фильтр не применён"
        sl = df_cut.loc[df_cut.index >= pB[0] + pd.Timedelta(rule)]
        if sl.empty:
            frac = 0.0
        elif pB[3] == "up":
            frac = (pB[2] - float(sl["low"].min())) / leg_len
        else:
            frac = (float(sl["high"].max()) - pB[2]) / leg_len
        ld = 1 if pB[3] == "up" else -1
        direction = str(sig.get("direction") or "")
        same_leg = (ld == 1 and direction == "LONG") or (ld == -1 and direction == "SHORT")
        verdict = "chase" if (same_leg and frac < ELLIOTT_FRAC) else "ok"
        reason = (f"откат {frac:.2f} от {'up' if ld == 1 else 'down'}-ноги"
                  + (" — гонка" if verdict == "chase" else " — ок"))
        return {"zz_last_dir": ld, "zz_frac": round(float(frac), 4), "verdict": verdict}, reason
    except Exception as e:
        return None, f"elliott: ошибка {e!r} — фильтр не применён"
```
*(np импортирован на уровне модуля (стр. 31) — доп. импорты не нужны.)*

## Правка 3. Вызов — в `_run_detect_and_trade`, внутри цикла по сигналам (строки 11673–11692)

ДО (хвост vwap-блока):
```python
            continue
        kept.append(sig)
    if not kept:
```
ПОСЛЕ:
```python
            continue
        if ELLIOTT_ENABLED:
            ef, e_reason = _elliott_features(df, tf_name, sig)
            if ef:
                sig["zz_last_dir"] = ef["zz_last_dir"]
                sig["zz_frac"] = ef["zz_frac"]
                sig["zz_verdict"] = ef["verdict"]
                if ef["verdict"] == "chase" and ELLIOTT_APPLY_SKIP:
                    logger.info(
                        f"elliott skip {active_symbol_key()} {sig.get('direction')} "
                        f"[{tf_name}] {e_reason}"
                    )
                    await _notify_signal_skip(
                        sig, tf_name, "skipped_elliott",
                        header=(
                            f"{_mode_prefix()} ⛔ Пропуск {sig.get('direction')} "
                            f"[{tf_label(tf_name)}] {symbol_profile()['label']} — эллиотт (гонка)"
                        ),
                        detail=e_reason,
                    )
                    continue
        kept.append(sig)
    if not kept:
```
*(при `ELLIOTT_APPLY_SKIP=False` — ЭТАП 1: фичи просто кладутся в sig и едут дальше в карточку/журнал.)*
*Проверено: `_notify_signal_skip` (стр. 9188) принимает произвольную `category` — подходит.*

## Правка 4. PendingLimit — поля + сериализация (строки 956–958, 1011–1015, 1057–1058)

- после `self.cvd_weight: Optional[float] = None` (стр. 957) добавить:
```python
        self.zz_last_dir: int = 0
        self.zz_frac: Optional[float] = None
        self.zz_verdict: str = ""
```
- в `to_dict` после блока `cvd_weight` (стр. 1013–1014) добавить:
```python
        if self.zz_frac is not None:
            d["zz_last_dir"] = self.zz_last_dir
            d["zz_frac"] = self.zz_frac
            d["zz_verdict"] = self.zz_verdict or None
```
- в `from_dict` после `p.cvd_weight = ...` (стр. 1058) добавить:
```python
        p.zz_last_dir = int(d.get("zz_last_dir") or 0)
        p.zz_frac = _safe_float(d.get("zz_frac"))
        p.zz_verdict = str(d.get("zz_verdict") or "")
```

## Правка 5. Position — те же три поля (для журнала закрытых; строки 814–815, 855–858, 902–903, 6212–6213)

- стр. 815+: `self.zz_last_dir: int = 0` / `self.zz_frac: Optional[float] = None` / `self.zz_verdict: str = ""`
- `to_dict` (после 857): аналог блока из Правки 4
- `from_dict` (после 903): аналог
- копирование при переходе pending→position (после стр. 6213):
```python
    pos.zz_last_dir = int(getattr(pl, "zz_last_dir", 0) or 0)
    pos.zz_frac = _safe_float(getattr(pl, "zz_frac", None))
    pos.zz_verdict = str(getattr(pl, "zz_verdict", "") or "")
```

## Правка 6. `create_pending_limit` — прокинуть фичи из sig (после стр. 9775 `pl.cvd_weight = cvd_w`)

```python
    pl.zz_last_dir = int(sig.get("zz_last_dir") or 0)
    pl.zz_frac = _safe_float(sig.get("zz_frac"))
    pl.zz_verdict = str(sig.get("zz_verdict") or "")
```

## Правка 7. Карточка заявки (в блоке cvd_line, стр. 8560; вывод — после стр. 8571)

ДО:
```python
        cvd_line += "\n"
```
ПОСЛЕ:
```python
        cvd_line += "\n"
    zz_ln = ""
    if sig.get("zz_frac") is not None:
        zz_dir = "up" if int(sig.get("zz_last_dir") or 0) == 1 else "down"
        zz_ln = f"Эллиотт: откат {float(sig['zz_frac']):.2f} от {zz_dir}-ноги"
        if sig.get("zz_verdict") == "chase":
            zz_ln += " → гонка" + ("" if ELLIOTT_APPLY_SKIP else " (shadow)")
        zz_ln += "\n"
```
и в сборке `msg` после `f"{cvd_line}"` (стр. 8571) вставить строкой:
```python
        f"{zz_ln}"
```

## Правка 8. Журнал — записи `pending_created` и `closed`

- `_pending_journal_record` после стр. 6129 (`"cvd_weight"`):
```python
        "zz_last_dir": getattr(pl, "zz_last_dir", None),
        "zz_frac": getattr(pl, "zz_frac", None),
        "zz_verdict": getattr(pl, "zz_verdict", "") or None,
```
- `_position_journal_record` после стр. 6186: аналогично через `getattr(pos, ...)`.

## Опционально: `/elliott` тумблер

По образцу `/cvd` (state-поле стр. 539, save/load 1138/1258, BotCommand 3296, handler 3366, /status 4559; `cmd_cvd` — образец). Для ЭТАП 1 не обязателен — можно позже.

---

## Сопряжённые правки — чек-лист

1. `python -m py_compile cisdbot.py`
2. `grep -n "zz_last_dir\|zz_frac\|zz_verdict" cisdbot.py` → должны быть во ВСЕХ точках: конфиг, `_elliott_features`/`_zigzag`, вызов (правка 3), PendingLimit (def/to/from), Position (def/to/from/copy), create_pending (×3), карточка (через sig), журнал (×2).
3. Правки НЕ трогают `backtest/*.py` — гейт только в live; бэк-числа — от прототипа `_elliott_proxy_v1.py`.
4. `state.df_cache` НЕ трогаем; новых stateful-полей нет → save/load не меняется.
5. В header skip-нотификации — `symbol_profile()['label']` без аргумента (как в vwap-блоке).
6. Деплой по обычной процедуре: `py_compile` → бэкап → scp → md5 → рестарт → проверить чистый старт и свежие сканы без Traceback.

## Этапы

- **ЭТАП 1 (сейчас):** `ELLIOTT_APPLY_SKIP=False` — считаем фичи, пишем в журнал + карточку, ничего не режем. Сравниваем живые значения с пересчётом из тех же свечей (2–4 недели).
- **ЭТАП 2:** `ELLIOTT_APPLY_SKIP=True`.
- **ПЕРЕД ЭТАПОМ 2 (рекомендация):** каузальный пересчёт фич на бэктесте — прототип мерил frac по полным HTF-бакетам (включая данные ПОСЛЕ момента решения внутри текущего бакета), live строже. Ожидание: направление эффекта сохранится, величина слегка сдвинется. Запросить у ассистента: «пересчитай эллиотт каузально» (~30 мин).

## Известные оговорки

- ZigZag у порога 2 пивотов чувствителен к окну истории: df5 = 1000 баров (~3.5 дней ≈ 20 бакетов 4h) — хватает; при `шли мало пивотов` в логе — поднять `OHLCV_5M_BARS`.
- Fallback везде мягкий: без данных фильтр не применяется (торговля не встаёт), в лог/журнал идёт reason.
- Эффект скромный (+222R/7 лет ≈ +3R/мес): это «гигиена» WR, не второй «пороговый» рычаг.

---

# ЧАСТЬ 2 (вечер 14.09, по итогам программы): слой «моментум + KC» — БОЛЬШЕ chase

> ⏸ **НА ПАУЗЕ (якорь):** числа KC-клетки (−471R) и r1-бандов посчитаны на `decision_at` (+26/60 мин после конфирма, ПОСЛЕ филла) — не лайв-якорь. Ни shadow-фичи, ни SKIP не внедрять до пересчёта (`_q_reanchor.py`); канон: `cryptofish-research → references/lookahead-traps.md`.

Найден блок крупнее Эллиотта: `KC<0 & r1<0.002` → −471R (минус 7/7 лет). Обе фичи считаются из УЖЕ загруженного df — ноль внешних данных/запросов.
Порядок внедрения: shadow-фичи → SKIP KC-cell → SKIP chase.

## 2.1. Конфиг (рядом с ELLIOTT-блоком, после ELLIOTT_THETA)
```python
MOM_ENABLED      = True
MOM_SHADOW       = True    # ЭТАП 1: только фичи в карточку/журнал
MOM_R1_EDGE      = 0.002   # замороженная граница r1 (фит 2020-23)
MOM_KC_MULT      = 1.5     # ATR-множитель KC (как в скрине)
MOM_KC_CELL_SKIP = False   # ЭТАП 2: True → SKIP «KC<0 & r1<edge»
```

## 2.2. Функция `_mom_features(df, tf_name, sig)` — вставить после `_elliott_features`
```python
def _mom_features(df: pd.DataFrame, tf_name: str, sig: dict) -> tuple[Optional[dict], str]:
    """r1_s (ход цены за 1ч в сторону сделки) и kc_pos_s (close vs EMA20 в ATR, знак в сторону).
    Считается по ЗАКРЫТЫМ барам df (последний = confirm-бар). Без внешних данных."""
    from backtest.sweep_atr_filter import compute_atr14
    try:
        scan_raw = sig.get("confirm_bar_time") or sig.get("timestamp")
        df_cut = df
        if scan_raw:
            ts = pd.Timestamp(scan_raw)
            if getattr(ts, "tzinfo", None) is not None:
                ts = ts.tz_convert("UTC").tz_localize(None) if ts.tzinfo else ts.tz_localize(None)
            df_cut = df.loc[:ts]
        tfm = 5 if tf_name == "tf7" else 30
        need = int(60 / tfm)
        if df_cut is None or len(df_cut) < need + 21:
            return None, "mom: мало баров — фильтр не применён"
        cl = float(df_cut["close"].iloc[-1])
        cl_1h = float(df_cut["close"].iloc[-1 - need])
        e20 = float(df_cut["close"].ewm(span=20, adjust=False).mean().iloc[-1])
        atr = compute_atr14(df_cut)
        a = float(atr.iloc[-1])
        if not (a > 0) or cl_1h <= 0:
            return None, "mom: ATR/цена недоступны"
        sgn = 1.0 if str(sig.get("direction")) == "LONG" else -1.0
        r1_s = (cl / cl_1h - 1.0) * sgn
        kc_s = ((cl - e20) / (MOM_KC_MULT * a)) * sgn
        cell = (kc_s < 0) and (r1_s < MOM_R1_EDGE)
        reason = (f"r1={r1_s*100:+.2f}%/1ч  KC={kc_s:+.2f} ATR"
                  + (" — контр-вход+моментум против (карантин)" if cell else " — ок"))
        return {"r1_s": r1_s, "kc_s": kc_s, "cell": cell}, reason
    except Exception as e:
        return None, f"mom: ошибка {e!r} — фильтр не применён"
```
*(ВАЖНО: в боте df включает формирующийся бар, но `df.loc[:confirm_bar_time]` отрезает ровно на confirm — его close уже известен, это и есть «последний закрытый». Совпадает с бэктест-семантикой.)*

## 2.3. Вызов — в `_run_detect_and_trade`, ПОСЛЕ Эллиотт-блока, перед `kept.append(sig)`
```python
        if MOM_ENABLED:
            mf, m_reason = _mom_features(df, tf_name, sig)
            if mf:
                sig["mom_r1_s"] = mf["r1_s"]
                sig["mom_kc_s"] = mf["kc_s"]
                if mf["cell"] and MOM_KC_CELL_SKIP:
                    logger.info(f"mom skip {active_symbol_key()} {sig.get('direction')} [{tf_name}] {m_reason}")
                    await _notify_signal_skip(
                        sig, tf_name, "skipped_mom",
                        header=(f"{_mode_prefix()} ⛔ Пропуск {sig.get('direction')} "
                                f"[{tf_label(tf_name)}] {symbol_profile()['label']} — контр-вход+моментум"),
                        detail=m_reason,
                    )
                    continue
        kept.append(sig)
```

## 2.4. Карточка/журнал/поля — по образцу части 1 (те же точки)
- Карточка (после zz_ln): `Моментум: {r1_s:+.2%}/1ч, KC {kc_s:+.2f} ATR` + «(shadow)»/«карантин», когда применимо.
- PendingLimit/Position: поля `mom_r1_s`, `mom_kc_s` (def / to_dict / from_dict / копия pending→pos) + в `_pending_journal_record`/`_position_journal_record` — как `zz_*`.
- `create_pending_limit`: `pl.mom_r1_s = _safe_float(sig.get("mom_r1_s")); pl.mom_kc_s = _safe_float(sig.get("mom_kc_s"))`.

## 2.5. Чек-лист стыковки (из части 1 — тот же)
`py_compile`; grep `mom_r1_s|mom_kc_s` по всем точкам; fallback везде мягкий; SHADOW 2-4 недели → сверка фич live vs бэк → ЭТАП 2 (сначала `MOM_KC_CELL_SKIP`, потом `ELLIOTT_APPLY_SKIP`).

## 2.6. Ожидание (бэктест 2020-26)
- KC-cell skip: −471R уходит (все 7 лет минус), режет 10.5%.
- chase skip: −220R, режет 7.5%. Вместе: −547R, остаток WR 74.8% / ΣR +5976.
- (Опционально слой весов r1 0.7/1.0/1.3 — только ПОСЛЕ скипов и отдельной перепроверки: см. отчёт.)

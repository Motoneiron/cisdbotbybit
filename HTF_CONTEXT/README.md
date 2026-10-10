# HTF_CONTEXT — причинный слой карты старших ТФ (этап 1: датасет, без решений)

Модуль для каждого LTF-сигнала бота (tf1: 15m→4H, кандидат v2) строит **causal-карту
рынка на момент решения**: какие подтверждённые и ещё актуальные объекты старших ТФ
(4H/1D/1W) существовали в этот момент, где они относительно цены, направления сделки,
стопа и тейка.

**Модуль НЕ принимает торговых решений**: ни фильтров, ни ML, ни LLM, ни порогов.
Только контекст + исследовательский датасет.

## Гарантии причинности (no-lookahead)

- Все признаки считаются только по барам с `close_time <= decision_time`
  (для сигналов кандидата `decision_time = scan = конфирм-бар + 15 минут`).
- FVG доступен после закрытия третьей свечи; свинг — после закрытия правой подтверждающей.
- Состояния объектов (fill/swept/broken) рассчитываются на момент сигнала, а не на конец истории.
- Незавершённая HTF-свеча не используется (её close > decision_time).
- Проверка: `htf_validate.py` — тесты 1–5 (синтетика) + **truncation invariance**
  (контекст на полном датасете обязан бит-в-бит совпасть с контекстом на датасете,
  обрезанном по `close <= t`) на синтетике и на реальных данных SOL.

## Объекты и признаки

- **FVG** (строгий 3-свечной wick): bullish `low[i] > high[i-2]`, bearish `high[i] < low[i-2]`.
  Состояния: `ACTIVE` / `PARTIALLY_FILLED` (fill_pct) / `FILLED`. Дистанция до FVG считается
  до ближайшей границы **остаточной (незаполненной) части** зоны: `FVG_BULL: [lo, min_low_since]`,
  `FVG_BEAR: [max_high_since, hi]`. Полностью пройденная часть ценой не является препятствием;
  если остаток целиком «за спиной» — объект не препятствие; если остаток накрывает entry — `straddle` (0.0).
- **Свинги** (3-свечные): `SWING_HIGH` / `SWING_LOW`. Состояния: `ACTIVE` / `SWEPT`
  (фитиль за уровнем) / `BROKEN` (закрытие за уровнем). Пройденные — не препятствия.
- **PDH/PDL/PWH/PWL** — только завершённые день/неделя.
- **Dealing range** по последним подтверждённым свингам каждого ТФ (+ PREMIUM/DISCOUNT).
- **Path map**: препятствия по направлению сделки, отсортированные по дистанции;
  `nearest_opposing_obstacle_R/_pct`, `nearest_internal_liquidity_R` (FVG),
  `nearest_external_liquidity_R` (свинги + PDH/PWH), счётчики по корзинам
  `<0.5 / 0.5-1 / 1-2 / 2-3R`, `tp_blocked` (производный для fixed TP).
- **Исключение source-уровня** (§6): `htf_sweep_level` сигнала не может быть препятствием —
  строгий матчинг (2 bps) по уровню свинга / границе зоны FVG на ТФ 4H. Широкий матчинг
  «зона содержит уровень» отвергнут: он вырезал десятки старых зон и искажал карту.

## Файлы

```
HTF_CONTEXT/
  htf_resample.py          загрузка 1m → 4H/1D/1W (label/closed=left; недели W-MON)
  htf_fvg.py               детектор FVG
  htf_swings.py            детектор свингов
  htf_objects.py           HTFObject (causal-атрибуты: created/known/available)
  htf_state.py             инкрементальная as-of машина состояний (fill/sweep/break)
  htf_reference_levels.py  PDH/PDL/PWH/PWL
  htf_range.py             dealing range
  htf_path.py              карта пути + признаки
  htf_context.py           HTFContextEngine: context(decision_time, signal) → JSON
  htf_validate.py          sanity-тесты (§15) + truncation invariance
  research_htf_context.py  сборка датасета + отчёт (§14)
```

## Запуск

Интерпретатор — только `D:/PYTHON/CISDBOT/.venv/Scripts/python.exe`, cwd = `D:\PYTHON\cisdbotbybit`.

```powershell
# 1) sanity-тесты
python -m HTF_CONTEXT.htf_validate
#   → RUNS/cache/htf_context_validation.json

# 2) датасет + отчёт (после прогона RUNS/temp/live_tf_htfctx/rows_tf1v2/*.pkl)
python -m HTF_CONTEXT.research_htf_context
#   → RUNS/cache/htf_context.jsonl          контекст на каждый сигнал
#   → RUNS/cache/htf_context_summary.csv    плоские признаки
#   → RUNS/HTF_CONTEXT_REPORT_2026-10-08.md анализ (§14)

# только пересборка отчёта по готовому JSONL
python -m HTF_CONTEXT.research_htf_context --skip-build
```

Источник сигналов: `RUNS/temp/htfctx_run.py` — копия эталона `stop_timing_run.py`
(логика решений 1:1, n=998, ΣR=+113.3), дополненная дампом `cisd_level`,
`htf_sweep_level`, `trigger_extreme`, `base_high/low` и строками пропущенных
сигналов (`taken=False`, контрфактический исход `outcome_cf/r_cf`).

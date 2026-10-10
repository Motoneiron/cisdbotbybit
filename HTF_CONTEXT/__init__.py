# -*- coding: utf-8 -*-
"""HTF Context Engine — причинный слой карты старших ТФ (4H/1D/1W) для LTF-сигналов.

Собирает на момент решения (decision_time) только те объекты и состояния,
которые существовали и были известны в этот момент: FVG, свинги, PDH/PDL/PWH/PWL,
dealing range и карту пути сделки (nearest_opposing_obstacle_R и др.).

Этап 1: контекст + исследовательский датасет. Движок НЕ принимает торговых решений.
"""
from __future__ import annotations

from .htf_context import HTFContextEngine, SourceExclusion
from .htf_fvg import detect_fvgs
from .htf_objects import HTFObject
from .htf_path import MAX_PATH_R, collect_obstacles, summarize_features
from .htf_range import dealing_range
from .htf_reference_levels import reference_levels
from .htf_resample import TF_MINUTES, TF_RULES, load_1m, make_frames, resample_ohlcv
from .htf_state import TFTracker
from .htf_swings import detect_swings

__all__ = [
    "HTFContextEngine", "SourceExclusion",
    "HTFObject", "TFTracker",
    "detect_fvgs", "detect_swings",
    "collect_obstacles", "summarize_features", "MAX_PATH_R",
    "dealing_range", "reference_levels",
    "load_1m", "make_frames", "resample_ohlcv", "TF_MINUTES", "TF_RULES",
]

# -*- coding: utf-8 -*-
"""HTF Context Engine — объект старшего ТФ (FVG / swing) с causal-атрибутами.

Индексы ниже — в координатах баров СВОЕГО ТФ-фрейма:
  * created_idx — бар формирования: третья свеча FVG / средняя свеча свинга;
  * known_idx   — первый ЗАКРЫТЫЙ бар, на котором объект уже известен:
                  FVG  — bar i (после закрытия третьей свечи),
                  swing — bar i+1 (после закрытия правой подтверждающей свечи);
  * scan_start  — первый бар, чьи экстремумы учитываются в состоянии объекта:
                  FVG — i+1, swing — i+2 (бар подтверждения не может «свипнуть» свой же уровень).

available_at = close_time(created-бара) для FVG и close_time(правого бара) для свинга.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

FVG_KINDS = ("FVG_BULL", "FVG_BEAR")
SWING_KINDS = ("SWING_HIGH", "SWING_LOW")


@dataclass
class HTFObject:
    tf: str                     # "4H" | "1D" | "1W"
    kind: str                   # FVG_BULL | FVG_BEAR | SWING_HIGH | SWING_LOW
    created_idx: int
    known_idx: int
    scan_start: int
    created_at: pd.Timestamp
    available_at: pd.Timestamp
    lo: float | None = None     # FVG: нижняя граница зоны
    hi: float | None = None     # FVG: верхняя граница зоны
    level: float | None = None  # swing: уровень
    src: str = ""               # происхождение ("fvg3" | "swing3")

    def is_fvg(self) -> bool:
        return self.kind in FVG_KINDS

    def is_swing(self) -> bool:
        return self.kind in SWING_KINDS

    def price_lo(self) -> float:
        """Нижняя цена объекта (для зон — lo, для свингов — level)."""
        return float(self.lo if self.is_fvg() else self.level)

    def price_hi(self) -> float:
        """Верхняя цена объекта."""
        return float(self.hi if self.is_fvg() else self.level)

    def to_dict(self) -> dict:
        d = {
            "tf": self.tf,
            "kind": self.kind,
            "created_at": str(self.created_at),
            "available_at": str(self.available_at),
        }
        if self.is_fvg():
            d["lo"] = round(float(self.lo), 10)
            d["hi"] = round(float(self.hi), 10)
        else:
            d["level"] = round(float(self.level), 10)
        return d

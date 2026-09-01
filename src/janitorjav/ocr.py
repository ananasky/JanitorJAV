from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Sequence


@dataclass(frozen=True, slots=True)
class OCRLine:
    text: str
    confidence: float
    bounding_box: tuple[tuple[float, float], ...] = ()


class OCREngine(Protocol):
    @property
    def name(self) -> str: ...

    def recognize(self, image_paths: Sequence[Path]) -> list[list[OCRLine]]:
        """Return one list of OCR lines per input image, preserving input order."""
        ...


class OCRConfigurationError(RuntimeError):
    pass


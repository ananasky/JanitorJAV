from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

from .ocr import OCRConfigurationError, OCRLine


class PaddleOCREngine:
    """PaddleOCR 3.x adapter loaded lazily so the core remains lightweight."""

    name = "paddleocr"

    def __init__(self, *, device: str = "gpu:0", language: str = "ch") -> None:
        try:
            from paddleocr import PaddleOCR
        except ImportError as error:
            raise OCRConfigurationError(
                "PaddleOCR is not installed. Run scripts/install-paddle-gpu.ps1 on Windows."
            ) from error
        try:
            self._ocr = PaddleOCR(
                lang=language,
                device=device,
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
            )
        except Exception as error:
            raise OCRConfigurationError(f"Unable to initialize PaddleOCR on {device}: {error}") from error

    def recognize(self, image_paths: Sequence[Path]) -> list[list[OCRLine]]:
        output: list[list[OCRLine]] = []
        for path in image_paths:
            try:
                results = list(self._ocr.predict(input=str(path)))
            except Exception as error:
                raise RuntimeError(f"PaddleOCR failed for {path}: {error}") from error
            lines: list[OCRLine] = []
            for result in results:
                payload = _result_payload(result)
                texts = payload.get("rec_texts", [])
                scores = payload.get("rec_scores", [])
                boxes = payload.get("dt_polys", payload.get("rec_polys", []))
                for index, text in enumerate(texts):
                    score = float(scores[index]) if index < len(scores) else 0.0
                    box = _box_tuple(boxes[index]) if index < len(boxes) else ()
                    lines.append(OCRLine(str(text), score, box))
            output.append(lines)
        return output


def _result_payload(result: Any) -> dict[str, Any]:
    payload = getattr(result, "json", None)
    if callable(payload):
        payload = payload()
    if payload is None and isinstance(result, dict):
        payload = result
    if not isinstance(payload, dict):
        return {}
    inner = payload.get("res")
    return inner if isinstance(inner, dict) else payload


def _box_tuple(value: Any) -> tuple[tuple[float, float], ...]:
    try:
        return tuple((float(point[0]), float(point[1])) for point in value)
    except (TypeError, ValueError, IndexError):
        return ()


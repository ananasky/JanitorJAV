from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from enum import StrEnum


class MatchType(StrEnum):
    DOMAIN_LIKE = "domain_like"
    IPV4 = "ipv4"


class EvidenceLevel(StrEnum):
    POSSIBLE = "possible"
    HIGH = "high"


@dataclass(frozen=True, slots=True)
class DetectionMatch:
    match_type: MatchType
    raw_text: str
    normalized_text: str
    confidence: float
    evidence_level: EvidenceLevel
    start: int
    end: int


_DOT_TRANSLATION = str.maketrans({"。": ".", "．": ".", "｡": "."})
_POINT_TEXT = re.compile(
    r"(?<![\w-])"
    r"(?P<value>"
    r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)"
    r"(?:\s*\.\s*(?:[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?))+"
    r")"
    r"(?![\w-])"
)


def normalize_ocr_text(text: str) -> str:
    text = text.translate(_DOT_TRANSLATION)
    return re.sub(r"\s*\.\s*", ".", text)


def detect_point_text(
    text: str,
    *,
    confidence: float,
    high_confidence_threshold: float = 0.75,
) -> list[DetectionMatch]:
    normalized = normalize_ocr_text(text)
    results: list[DetectionMatch] = []

    for match in _POINT_TEXT.finditer(normalized):
        value = match.group("value")
        labels = value.split(".")
        if len(labels[-1]) < 2:
            continue

        match_type = MatchType.DOMAIN_LIKE
        try:
            address = ipaddress.ip_address(value)
            if address.version == 4:
                match_type = MatchType.IPV4
        except ValueError:
            pass

        level = (
            EvidenceLevel.HIGH
            if confidence >= high_confidence_threshold
            else EvidenceLevel.POSSIBLE
        )
        results.append(
            DetectionMatch(
                match_type=match_type,
                raw_text=match.group("value"),
                normalized_text=value,
                confidence=confidence,
                evidence_level=level,
                start=match.start("value"),
                end=match.end("value"),
            )
        )
    return results


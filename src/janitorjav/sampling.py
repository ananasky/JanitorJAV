from __future__ import annotations

from dataclasses import dataclass, field


ABSOLUTE_SECONDS = (5.0, 10.0, 15.0, 20.0, 25.0)
RELATIVE_POSITIONS = (0.10, 0.25, 0.50, 0.75, 0.90)


@dataclass(slots=True)
class SamplePoint:
    timestamp_seconds: float
    sources: list[str] = field(default_factory=list)


def calculate_sample_points(
    duration_seconds: float,
    *,
    merge_tolerance_seconds: float = 0.5,
) -> list[SamplePoint]:
    if duration_seconds <= 0:
        return []

    candidates: list[SamplePoint] = []
    for seconds in ABSOLUTE_SECONDS:
        if seconds < duration_seconds:
            candidates.append(SamplePoint(seconds, [f"{seconds:g}s"]))
    for fraction in RELATIVE_POSITIONS:
        timestamp = duration_seconds * fraction
        if 0 <= timestamp < duration_seconds:
            candidates.append(SamplePoint(timestamp, [f"{fraction:.0%}"]))

    candidates.sort(key=lambda point: point.timestamp_seconds)
    merged: list[SamplePoint] = []
    for candidate in candidates:
        if merged and candidate.timestamp_seconds - merged[-1].timestamp_seconds <= merge_tolerance_seconds:
            merged[-1].sources.extend(candidate.sources)
            continue
        merged.append(candidate)
    return merged


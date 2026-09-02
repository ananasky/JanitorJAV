from __future__ import annotations

import re
from typing import Any


PROMOTIONAL_KEYWORDS = frozenset(
    {
        "博彩",
        "赌场",
        "娱乐城",
        "棋牌",
        "投注",
        "下注",
        "送彩金",
        "注册送",
        "代理",
        "客服",
        "免费获取",
        "国产大片",
        "澳门",
    }
)


def evidence_score(record: dict[str, Any]) -> tuple[int, str, list[dict[str, Any]]]:
    aggregates: dict[str, dict[str, Any]] = {}
    all_lines: list[str] = []

    for video_index, video in enumerate(record.get("videos", [])):
        for frame_index, frame in enumerate(video.get("frames", [])):
            frame_key = (video_index, frame_index)
            lines = _text_lines(frame.get("ocr_text", ""))
            all_lines.extend(lines)
            for match in frame.get("matches", []):
                value = str(match.get("normalized_text") or match.get("raw_text") or "").strip()
                if not value:
                    continue
                key = value.casefold()
                item = aggregates.setdefault(
                    key,
                    {
                        "text": value,
                        "match_type": match.get("type", match.get("match_type", "domain_like")),
                        "frames": set(),
                        "positions": [],
                        "confidence": 0.0,
                        "related_text": [],
                    },
                )
                item["frames"].add(frame_key)
                for position in frame.get("requested_positions", []):
                    if position not in item["positions"]:
                        item["positions"].append(position)
                item["confidence"] = max(item["confidence"], float(match.get("confidence") or 0))
                for line in lines:
                    if line.casefold() != key and line not in item["related_text"]:
                        item["related_text"].append(line)

    has_promotion = any(keyword in line for keyword in PROMOTIONAL_KEYWORDS for line in all_lines)
    summaries: list[dict[str, Any]] = []
    for item in aggregates.values():
        frame_count = len(item.pop("frames"))
        strong_format = _is_strong_address(item["text"], item["match_type"])
        related = sorted(
            item.pop("related_text"),
            key=lambda line: (not any(keyword in line for keyword in PROMOTIONAL_KEYWORDS), len(line)),
        )
        score = (30 if strong_format else 5) + min(frame_count, 6) * 7
        score += 15 if item["confidence"] >= 0.75 else round(item["confidence"] * 10)
        if has_promotion:
            score = 200
        elif not strong_format:
            score = min(score, 35)
        summaries.append(
            {
                **item,
                "frame_count": frame_count,
                "related_text": related[:3],
                "strong_format": strong_format,
                "score": min(100, score) if not has_promotion else 200,
            }
        )

    summaries.sort(key=lambda item: (-item["score"], -item["frame_count"], item["text"].casefold()))
    highest = max((item["score"] for item in summaries), default=0)
    score = 200 if highest == 200 else min(100, highest + min(6, max(0, len(summaries) - 1) * 2))
    label = "high" if score >= 70 else "medium" if score >= 45 else "low"
    return score, label, summaries


def _is_strong_address(value: str, match_type: str) -> bool:
    if match_type == "ipv4":
        return True
    final_label = value.rsplit(".", 1)[-1]
    return bool(re.fullmatch(r"[A-Za-z]{2,24}", final_label))


def _text_lines(value: str) -> list[str]:
    result: list[str] = []
    for raw in value.splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if line and line not in result:
            result.append(line[:160])
    return result

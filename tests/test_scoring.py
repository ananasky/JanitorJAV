from janitorjav.scoring import evidence_score


def _record(value: str, *, frames: int, text: str = "") -> dict:
    return {
        "videos": [
            {
                "frames": [
                    {
                        "requested_positions": [f"{index * 10}%"],
                        "ocr_text": f"{text}\n{value}".strip(),
                        "matches": [
                            {
                                "type": "domain_like",
                                "normalized_text": value,
                                "confidence": 0.95,
                            }
                        ],
                    }
                    for index in range(1, frames + 1)
                ]
            }
        ]
    }


def test_evidence_is_aggregated_across_frames() -> None:
    score, label, summaries = evidence_score(
        _record("www.22366.com", frames=6, text="澳门娱乐城 注册送彩金")
    )

    assert score == 200
    assert label == "high"
    assert summaries[0]["frame_count"] == 6
    assert summaries[0]["positions"] == ["10%", "20%", "30%", "40%", "50%", "60%"]
    assert "澳门娱乐城 注册送彩金" in summaries[0]["related_text"]


def test_numeric_pseudo_suffix_is_scored_lower_than_domain() -> None:
    strong_score, _, _ = evidence_score(_record("example.com", frames=6))
    weak_score, weak_label, summary = evidence_score(_record("DMM.R18", frames=6))

    assert strong_score > weak_score
    assert weak_score == 35
    assert weak_label == "low"
    assert summary[0]["strong_format"] is False


def test_promotional_keyword_forces_score_to_200_even_for_weak_address() -> None:
    score, label, _ = evidence_score(
        _record("DMM.R18", frames=1, text="澳门娱乐城 注册送彩金")
    )

    assert score == 200
    assert label == "high"


def test_live_casino_keywords_force_score_to_200() -> None:
    for keyword in (
        "真人美女",
        "荷官",
        "发牌",
        "裸聊",
        "脱衣秀",
        "激情视频",
        "漂亮妹妹",
        "幼幼",
        "人兽",
    ):
        score, label, _ = evidence_score(
            _record("example.com", frames=1, text=f"在线{keyword}")
        )
        assert score == 200
        assert label == "high"

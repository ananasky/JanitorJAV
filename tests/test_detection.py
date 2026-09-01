from janitorjav.detection import EvidenceLevel, MatchType, detect_point_text, normalize_ocr_text


def test_normalizes_full_width_and_spaced_dots() -> None:
    assert normalize_ocr_text("访问 abc 。 com 或 x．cn") == "访问 abc.com 或 x.cn"


def test_detects_two_character_suffix() -> None:
    matches = detect_point_text("请访问 ab.cd", confidence=0.91)
    assert len(matches) == 1
    assert matches[0].normalized_text == "ab.cd"
    assert matches[0].match_type is MatchType.DOMAIN_LIKE
    assert matches[0].evidence_level is EvidenceLevel.HIGH


def test_rejects_one_character_suffix() -> None:
    assert detect_point_text("not a.b", confidence=0.99) == []


def test_detects_ipv4_and_low_confidence() -> None:
    matches = detect_point_text("server 192.168.1.10", confidence=0.4)
    assert len(matches) == 1
    assert matches[0].match_type is MatchType.IPV4
    assert matches[0].evidence_level is EvidenceLevel.POSSIBLE


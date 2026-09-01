from janitorjav.sampling import calculate_sample_points


def test_long_video_has_all_ten_points() -> None:
    points = calculate_sample_points(600)
    assert [point.timestamp_seconds for point in points] == [
        5,
        10,
        15,
        20,
        25,
        60,
        150,
        300,
        450,
        540,
    ]


def test_short_video_discards_invalid_and_merges_close_points() -> None:
    points = calculate_sample_points(20)
    assert [point.timestamp_seconds for point in points] == [2, 5, 10, 15, 18]
    five_second_point = points[1]
    assert set(five_second_point.sources) == {"5s", "25%"}


def test_invalid_duration_has_no_points() -> None:
    assert calculate_sample_points(0) == []
    assert calculate_sample_points(-1) == []


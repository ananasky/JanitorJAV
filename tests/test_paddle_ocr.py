from pathlib import Path

from janitorjav.paddle_ocr import PaddleOCREngine


class FakeResult:
    def __init__(self, text: str) -> None:
        self.json = {
            "res": {
                "rec_texts": [text],
                "rec_scores": [0.95],
                "dt_polys": [[[0, 0], [10, 0], [10, 5], [0, 5]]],
            }
        }


class FakePaddle:
    def predict(self, *, input: list[str]):
        return [FakeResult(Path(value).stem) for value in input]


def test_recognize_batches_images_and_preserves_order(tmp_path: Path) -> None:
    engine = object.__new__(PaddleOCREngine)
    engine._ocr = FakePaddle()
    paths = [tmp_path / "first.jpg", tmp_path / "second.jpg"]

    result = engine.recognize(paths)

    assert [batch[0].text for batch in result] == ["first", "second"]
    assert result[0][0].confidence == 0.95
    assert result[0][0].bounding_box == ((0.0, 0.0), (10.0, 0.0), (10.0, 5.0), (0.0, 5.0))


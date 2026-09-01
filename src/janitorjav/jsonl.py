from __future__ import annotations

import json
import os
from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path
from typing import Any


def append_jsonl(path: Path, record: Mapping[str, Any], *, durable: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(payload)
        stream.flush()
        if durable:
            os.fsync(stream.fileno())


def read_jsonl(path: Path, *, tolerate_truncated_tail: bool = True) -> Iterator[dict[str, Any]]:
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as stream:
        lines = list(stream)
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            is_tail = index == len(lines) - 1
            if not (tolerate_truncated_tail and is_tail):
                raise


def write_jsonl(path: Path, records: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
            stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


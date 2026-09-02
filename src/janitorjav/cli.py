from __future__ import annotations

import argparse
import os
import webbrowser
from pathlib import Path

import uvicorn

from .paddle_ocr import PaddleOCREngine
from .task_manager import TaskManager
from .web import create_app


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="JanitorJAV local media review service")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8765, type=int)
    parser.add_argument("--device", default="gpu:0", help="PaddleOCR device, e.g. gpu:0 or cpu")
    parser.add_argument("--frame-workers", default=4, type=int, help="Concurrent FFmpeg frame extractions")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--pid-file", type=Path)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    engine = PaddleOCREngine(device=args.device)
    manager = TaskManager(engine, frame_workers=args.frame_workers)
    app = create_app(manager)
    if not args.no_browser:
        webbrowser.open(f"http://{args.host}:{args.port}")
    if args.pid_file:
        args.pid_file.parent.mkdir(parents=True, exist_ok=True)
        args.pid_file.write_text(str(os.getpid()), encoding="ascii")
    try:
        uvicorn.run(app, host=args.host, port=args.port)
    finally:
        if args.pid_file:
            args.pid_file.unlink(missing_ok=True)


if __name__ == "__main__":
    main()

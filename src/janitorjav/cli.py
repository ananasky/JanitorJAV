from __future__ import annotations

import argparse
import webbrowser

import uvicorn

from .paddle_ocr import PaddleOCREngine
from .task_manager import TaskManager
from .web import create_app


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="JanitorJAV local media review service")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8765, type=int)
    parser.add_argument("--device", default="gpu:0", help="PaddleOCR device, e.g. gpu:0 or cpu")
    parser.add_argument("--no-browser", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    engine = PaddleOCREngine(device=args.device)
    manager = TaskManager(engine)
    app = create_app(manager)
    if not args.no_browser:
        webbrowser.open(f"http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()


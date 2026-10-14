"""Owned loopback participant for the P012 finite score-scale grid.

The server loads the five synthetic labels and returns a fixed binary response
pattern. It loads no model and uses no inference library. Every response is a
SIMULATED fixture; only later validator decisions can be MEASURED.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


EXPECTED_ITEMS = 5
DECODE_BODY = {
    "temperature": 0.0,
    "top_k": 1,
    "top_p": 1.0,
    "n_predict": 64,
}


def normalized(value: str) -> str:
    return " ".join(value.strip().split()).lower()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mask", type=int, required=True)
    parser.add_argument("--evalset", type=Path, required=True)
    parser.add_argument("--ready", type=Path, required=True)
    parser.add_argument("--log", type=Path, required=True)
    args = parser.parse_args()

    if not 0 <= args.mask < (1 << EXPECTED_ITEMS):
        raise ValueError("mask must encode exactly five binary decisions")
    pairs = [
        json.loads(line)
        for line in args.evalset.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if len(pairs) != EXPECTED_ITEMS:
        raise ValueError("the frozen synthetic eval must have five items")
    by_prompt = {row["prompt"]: (index, row["answer"]) for index, row in enumerate(pairs)}
    if len(by_prompt) != EXPECTED_ITEMS:
        raise ValueError("synthetic prompts must be unique")

    with args.log.open("x", encoding="utf-8") as log:
        sequence = 0

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args) -> None:
                return None

            def reply(self, status: int, body: bytes) -> None:
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:
                body = b'{"status":"ok"}'
                self.reply(200 if self.path == "/health" else 404, body)

            def do_POST(self) -> None:
                nonlocal sequence
                started = time.monotonic()
                row = {
                    "evidence": "SIMULATED response fixture",
                    "mask": args.mask,
                    "sequence": sequence,
                    "status": "failed",
                }
                sequence += 1
                try:
                    size = int(self.headers.get("Content-Length", "0"))
                    if self.path != "/completion" or not 0 < size <= 100_000:
                        raise ValueError("unexpected request path or size")
                    raw = self.rfile.read(size)
                    request = json.loads(raw)
                    prompt = request.get("prompt")
                    if not isinstance(prompt, str) or request != {"prompt": prompt, **DECODE_BODY}:
                        raise ValueError("unexpected decode request")
                    if prompt not in by_prompt:
                        raise ValueError("prompt is outside the frozen synthetic eval")
                    item_index, answer = by_prompt[prompt]
                    intended_correct = bool(args.mask & (1 << item_index))
                    output = answer if intended_correct else f"P012 simulated wrong output {item_index}"
                    observed_prefix_match = normalized(output).startswith(normalized(answer))
                    if observed_prefix_match is not intended_correct:
                        raise AssertionError("fixture does not realize its binary oracle")
                    body = json.dumps({"content": output}, separators=(",", ":")).encode("utf-8")
                    row.update(
                        {
                            "intended_correct": intended_correct,
                            "item_index": item_index,
                            "observed_prefix_match": observed_prefix_match,
                            "output": output,
                            "prompt": prompt,
                            "request_body_sha256": hashlib.sha256(raw).hexdigest(),
                            "response_body_sha256": hashlib.sha256(body).hexdigest(),
                            "status": "ok",
                        }
                    )
                    status = 200
                except Exception as exc:  # preserve any failed attempt in the trace
                    row["error"] = {"type": type(exc).__name__, "message": str(exc)}
                    body = b'{"error":"participant failure"}'
                    status = 500
                row["elapsed_s"] = time.monotonic() - started
                log.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
                log.flush()
                self.reply(status, body)

        server = HTTPServer(("127.0.0.1", 0), Handler)
        server.timeout = 1
        with args.ready.open("x", encoding="utf-8") as ready:
            json.dump({"host": "127.0.0.1", "port": server.server_port}, ready)
        server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

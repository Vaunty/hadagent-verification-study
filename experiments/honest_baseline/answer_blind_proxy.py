"""Answer-blind loopback proxy for the honest-model baseline.

This process receives no evaluation file or labels. It forwards request and
response bodies byte-for-byte, writes raw evidence, and fsyncs one event before
returning each response.
"""
from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import time


def write_exclusive(path: Path, data: bytes) -> None:
    with path.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream-port", type=int, required=True)
    parser.add_argument("--listen-port", type=int, required=True)
    parser.add_argument("--ready", type=Path, required=True)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--max-requests", type=int, default=100)
    parser.add_argument("--upstream-timeout", type=float, default=115.0)
    args = parser.parse_args()
    if not 1 <= args.upstream_port <= 65535:
        raise ValueError("upstream must be an owned 127.0.0.1 port")
    if not 1 <= args.listen_port <= 65535 or args.listen_port == args.upstream_port:
        raise ValueError("listen port must be a distinct owned 127.0.0.1 port")
    if not 1 <= args.max_requests <= 100:
        raise ValueError("max requests must be between 1 and 100")
    if not 0 < args.upstream_timeout <= 115:
        raise ValueError("upstream timeout exceeds the frozen limit")
    args.raw_dir.mkdir(parents=False, exist_ok=False)
    counter = {"attempts": 0}

    with args.events.open("x", encoding="utf-8") as events:
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args: object) -> None:
                pass

            def reply(self, status: int, body: bytes, content_type: str) -> None:
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:  # noqa: N802
                body = b'{"status":"ok"}'
                self.reply(200 if self.path == "/health" else 404, body, "application/json")

            def do_POST(self) -> None:  # noqa: N802
                ordinal = counter["attempts"]
                counter["attempts"] += 1
                started = time.monotonic()
                row: dict[str, object] = {
                    "ordinal": ordinal,
                    "path": self.path,
                    "status": "failed",
                }
                request_body = b""
                response_body = b'{"error":"proxy failure"}'
                response_status = 502
                upstream_status: int | None = None
                response_type = "application/json"
                request_name = f"{ordinal:03d}.request.bin"
                response_name = f"{ordinal:03d}.response.bin"
                upstream_completed = False
                try:
                    if ordinal >= args.max_requests:
                        raise RuntimeError("request cap exceeded")
                    length = int(self.headers.get("Content-Length", "0"))
                    if self.path != "/completion" or not 0 < length <= 1_000_000:
                        raise ValueError("unexpected path or body size")
                    request_body = self.rfile.read(length)
                    if len(request_body) != length:
                        raise ValueError("incomplete request body")
                    connection = http.client.HTTPConnection(
                        "127.0.0.1", args.upstream_port, timeout=args.upstream_timeout
                    )
                    try:
                        connection.request(
                            "POST",
                            "/completion",
                            body=request_body,
                            headers={
                                "Content-Type": self.headers.get("Content-Type", "application/json"),
                                "Content-Length": str(len(request_body)),
                                "Connection": "close",
                            },
                        )
                        upstream = connection.getresponse()
                        upstream_status = upstream.status
                        response_type = upstream.getheader("Content-Type", "application/json")
                        try:
                            response_body = upstream.read()
                        except http.client.IncompleteRead as exc:
                            response_body = bytes(exc.partial)
                            raise
                        response_status = upstream_status
                        upstream_completed = True
                    finally:
                        connection.close()
                except Exception as exc:
                    row["error"] = {"type": type(exc).__name__, "message": str(exc)}
                try:
                    write_exclusive(args.raw_dir / request_name, request_body)
                    write_exclusive(args.raw_dir / response_name, response_body)
                    row.update(
                        upstream_http_status=upstream_status,
                        returned_http_status=response_status,
                        request_file=request_name,
                        response_file=response_name,
                        request_body_sha256=hashlib.sha256(request_body).hexdigest(),
                        response_body_sha256=hashlib.sha256(response_body).hexdigest(),
                    )
                    if upstream_completed:
                        row["status"] = "ok"
                except Exception as exc:
                    row["evidence_error"] = {"type": type(exc).__name__, "message": str(exc)}
                row["elapsed_s"] = time.monotonic() - started
                events.write(json.dumps(row, sort_keys=True) + "\n")
                events.flush()
                os.fsync(events.fileno())
                self.reply(response_status, response_body, response_type)

        server = HTTPServer(("127.0.0.1", args.listen_port), Handler)
        ready = json.dumps(
            {
                "host": "127.0.0.1",
                "port": server.server_port,
                "pid": os.getpid(),
                "upstream_host": "127.0.0.1",
                "upstream_port": args.upstream_port,
                "max_requests": args.max_requests,
            },
            sort_keys=True,
        ).encode("utf-8")
        write_exclusive(args.ready, ready)
        server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

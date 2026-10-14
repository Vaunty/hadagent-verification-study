from __future__ import annotations

import argparse
import http.client
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import hashlib
import subprocess
import sys
import threading
import time

from experiments.honest_baseline import run as baseline


ROOT = Path(__file__).resolve().parents[1]
PROXY = ROOT / "experiments/honest_baseline/answer_blind_proxy.py"
RUNNER = ROOT / "experiments/honest_baseline/run.py"
STUB = ROOT / "tests/honest_baseline_stub_server.py"


def test_answer_blind_proxy_preserves_bodies_and_flushes_evidence(tmp_path):
    seen = {}
    response_body = b'{ "content": "", "completion": "B", "timings": {"x": 1} }\n'

    class Upstream(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            length = int(self.headers["Content-Length"])
            seen["body"] = self.rfile.read(length)
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(response_body)))
            self.end_headers()
            self.wfile.write(response_body)

    upstream = HTTPServer(("127.0.0.1", 0), Upstream)
    thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    thread.start()
    ready = tmp_path / "ready.json"
    events = tmp_path / "events.jsonl"
    raw = tmp_path / "raw"
    process = subprocess.Popen(
        [
            sys.executable,
            "-B",
            "-X",
            "utf8",
            str(PROXY),
            "--upstream-port",
            str(upstream.server_port),
            "--listen-port",
            str(baseline.choose_port()),
            "--ready",
            str(ready),
            "--events",
            str(events),
            "--raw-dir",
            str(raw),
            "--max-requests",
            "1",
            "--upstream-timeout",
            "5",
        ],
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        deadline = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(process.stdout.read().decode())
            time.sleep(0.05)
        binding = json.loads(ready.read_text(encoding="utf-8"))
        request_body = b'{"prompt":"opaque input","temperature":0.0}'
        connection = http.client.HTTPConnection("127.0.0.1", binding["port"], timeout=5)
        connection.request(
            "POST",
            "/completion",
            body=request_body,
            headers={"Content-Type": "application/json"},
        )
        response = connection.getresponse()
        returned = response.read()
        connection.close()

        assert response.status == 200
        assert returned == response_body
        assert seen["body"] == request_body
        rows = [json.loads(line) for line in events.read_text(encoding="utf-8").splitlines()]
        assert len(rows) == 1 and rows[0]["status"] == "ok"
        assert rows[0]["upstream_http_status"] == rows[0]["returned_http_status"] == 200
        assert (raw / rows[0]["request_file"]).read_bytes() == request_body
        assert (raw / rows[0]["response_file"]).read_bytes() == response_body
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        upstream.shutdown()
        upstream.server_close()
        thread.join(5)


def test_model_run_requires_explicit_flag(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            "-X",
            "utf8",
            str(RUNNER),
            "run",
            "--plan",
            str(ROOT / "experiments/honest_baseline/plan.json"),
            "--output",
            str(tmp_path / "should-not-run"),
            "--expected-commit",
            "0" * 40,
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=10,
    )
    assert result.returncode != 0
    assert "--execute-model" in result.stdout
    assert not (tmp_path / "should-not-run").exists()


def test_proxy_failure_keeps_available_raw_evidence(tmp_path):
    ready = tmp_path / "ready.json"
    events = tmp_path / "events.jsonl"
    raw = tmp_path / "raw"
    upstream_port = baseline.choose_port()
    listen_port = baseline.choose_port()
    while listen_port == upstream_port:
        listen_port = baseline.choose_port()
    process = subprocess.Popen(
        [
            sys.executable, "-B", "-X", "utf8", str(PROXY),
            "--upstream-port", str(upstream_port),
            "--listen-port", str(listen_port),
            "--ready", str(ready), "--events", str(events),
            "--raw-dir", str(raw), "--max-requests", "1", "--upstream-timeout", "1",
        ],
        cwd=ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    try:
        deadline = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(process.stdout.read().decode())
            time.sleep(0.05)
        binding = json.loads(ready.read_text(encoding="utf-8"))
        request_body = b'{"prompt":"must survive upstream failure"}'
        connection = http.client.HTTPConnection("127.0.0.1", binding["port"], timeout=5)
        connection.request("POST", "/completion", body=request_body,
                           headers={"Content-Type": "application/json"})
        response = connection.getresponse()
        response_body = response.read()
        connection.close()
        row = json.loads(events.read_text(encoding="utf-8").strip())
        assert response.status == 502 and row["status"] == "failed"
        assert row["upstream_http_status"] is None and row["returned_http_status"] == 502
        assert (raw / row["request_file"]).read_bytes() == request_body
        assert (raw / row["response_file"]).read_bytes() == response_body
        assert row["request_body_sha256"] == hashlib.sha256(request_body).hexdigest()
        assert row["response_body_sha256"] == hashlib.sha256(response_body).hexdigest()
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)


def test_proxy_incomplete_upstream_body_preserves_partial_bytes_and_returns_502(tmp_path):
    partial_body = b'{"content":"par'

    class PartialUpstream(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            length = int(self.headers["Content-Length"])
            self.rfile.read(length)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(partial_body) + 20))
            self.end_headers()
            self.wfile.write(partial_body)
            self.wfile.flush()
            self.close_connection = True

    upstream = HTTPServer(("127.0.0.1", 0), PartialUpstream)
    thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    thread.start()
    ready = tmp_path / "ready.json"
    events = tmp_path / "events.jsonl"
    raw = tmp_path / "raw"
    process = subprocess.Popen(
        [
            sys.executable, "-B", "-X", "utf8", str(PROXY),
            "--upstream-port", str(upstream.server_port),
            "--listen-port", str(baseline.choose_port()),
            "--ready", str(ready), "--events", str(events),
            "--raw-dir", str(raw), "--max-requests", "1", "--upstream-timeout", "5",
        ],
        cwd=ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    try:
        deadline = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(process.stdout.read().decode())
            time.sleep(0.05)
        binding = json.loads(ready.read_text(encoding="utf-8"))
        request_body = b'{"prompt":"partial close"}'
        connection = http.client.HTTPConnection("127.0.0.1", binding["port"], timeout=5)
        connection.request("POST", "/completion", body=request_body,
                           headers={"Content-Type": "application/json"})
        response = connection.getresponse()
        returned = response.read()
        connection.close()
        row = json.loads(events.read_text(encoding="utf-8").strip())
        assert response.status == 502 and returned == partial_body
        assert row["status"] == "failed"
        assert row["upstream_http_status"] == 200 and row["returned_http_status"] == 502
        assert row["error"]["type"] == "IncompleteRead"
        assert (raw / row["response_file"]).read_bytes() == partial_body
        assert row["response_body_sha256"] == hashlib.sha256(partial_body).hexdigest()
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
        upstream.shutdown()
        upstream.server_close()
        thread.join(5)


def test_full_two_phase_orchestration_with_stub_model(tmp_path, monkeypatch):
    assert not baseline.EVAL_PATH.exists()
    rows = [json.dumps({"prompt": f"question {i}", "answer": "A"}) for i in range(100)]
    eval_bytes = ("\n".join(rows) + "\n").encode("utf-8")
    baseline.EVAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    with baseline.EVAL_PATH.open("xb") as handle:
        handle.write(eval_bytes)
    output = tmp_path / "two-phase"
    output.mkdir()
    plan = {
        "limits": {
            "phase_s": 30,
            "cleanup_reserve_s": 5,
            "max_total_requests": 200,
        }
    }
    assets = {
        "model": {"sha256": "11" * 32},
        "evalset": {
            "path": str(baseline.EVAL_PATH),
            "sha256": hashlib.sha256(eval_bytes).hexdigest(),
        },
    }
    monkeypatch.setattr(
        baseline,
        "runtime_command",
        lambda _assets, port: [sys.executable, "-B", "-X", "utf8", str(STUB), "--port", str(port)],
    )
    try:
        result = baseline.execute_two_phase(output, plan, assets, time.monotonic() + 60)
    finally:
        if baseline.EVAL_PATH.exists():
            baseline.EVAL_PATH.unlink()
    assert result["status"] == "ok"
    assert result["total_model_requests"] == 200
    assert result["same_proxy_port_both_phases"] is True
    assert result["ordered_request_bodies_equal"] is True
    assert result["metrics"]["claim"]["correct_under_normalized_prefix_scorer"] == 100
    assert result["metrics"]["validation"]["decision"] is True
    assert result["frozen_candidate"]["serialized_before_validation_phase"] is True


def test_worker_failure_still_writes_bounded_partial_audit(tmp_path, monkeypatch):
    assert not baseline.EVAL_PATH.exists()
    rows = [json.dumps({"prompt": f"question {i}", "answer": "A"}) for i in range(100)]
    eval_bytes = ("\n".join(rows) + "\n").encode("utf-8")
    baseline.EVAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    with baseline.EVAL_PATH.open("xb") as handle:
        handle.write(eval_bytes)
    output = tmp_path / "partial"
    output.mkdir()
    plan = {"limits": {"phase_s": 30, "cleanup_reserve_s": 5}}
    assets = {
        "evalset": {"path": str(baseline.EVAL_PATH)},
    }
    monkeypatch.setattr(
        baseline,
        "runtime_command",
        lambda _assets, port: [
            sys.executable, "-B", "-X", "utf8", str(STUB),
            "--port", str(port), "--malformed",
        ],
    )
    try:
        try:
            baseline.run_phase(
                "claim", output, plan, assets, time.monotonic() + 60, baseline.choose_port(),
            )
        except RuntimeError as exc:
            assert "worker failed" in str(exc)
        else:
            raise AssertionError("malformed model response should fail the worker")
    finally:
        if baseline.EVAL_PATH.exists():
            baseline.EVAL_PATH.unlink()
    audit = json.loads((output / "claim/proxy.audit.json").read_text(encoding="utf-8"))
    phase = json.loads((output / "claim/phase.json").read_text(encoding="utf-8"))
    assert audit["attempted_requests"] == 1
    assert audit["completed_requests"] == 1
    assert audit["successful_http_200_requests"] == 1
    assert audit["parsed_generation_responses"] == 0
    assert audit["complete"] is False and audit["issues"]
    assert phase["status"] == "failed"


def test_main_run_accepts_relative_plan_and_writes_complete_report(tmp_path, monkeypatch):
    assert not baseline.EVAL_PATH.exists()
    rows = [json.dumps({"prompt": f"question {i}", "answer": "A"}) for i in range(100)]
    eval_bytes = ("\n".join(rows) + "\n").encode("utf-8")
    asset_eval = tmp_path / "asset-eval.jsonl"
    asset_eval.write_bytes(eval_bytes)
    local_root = tmp_path / "local"
    output = local_root / "entrypoint"
    plan = {
        "limits": {
            "phase_s": 30,
            "global_s": 60,
            "cleanup_reserve_s": 5,
            "max_total_requests": 200,
        }
    }
    assets = {
        "model": {"sha256": "22" * 32},
        "evalset": {
            "path": str(asset_eval),
            "sha256": hashlib.sha256(eval_bytes).hexdigest(),
        },
    }
    expected_commit = baseline.p010.git("rev-parse", "HEAD")

    def fake_preflight(_plan_path, received_commit, _output, progress):
        assert received_commit == expected_commit
        progress.update(status="ok", commit=received_commit, test_stub=True)
        return progress

    monkeypatch.setattr(baseline, "LOCAL_ROOT", local_root)
    monkeypatch.setattr(baseline, "load_plan", lambda _path: (plan, assets))
    monkeypatch.setattr(baseline, "preflight", fake_preflight)
    monkeypatch.setattr(
        baseline,
        "runtime_command",
        lambda _assets, port: [sys.executable, "-B", "-X", "utf8", str(STUB), "--port", str(port)],
    )
    args = argparse.Namespace(
        plan=Path("experiments/honest_baseline/plan.json"),
        output=output,
        expected_commit=expected_commit,
    )
    try:
        exit_code = baseline.main_run(args)
    finally:
        if baseline.EVAL_PATH.exists():
            baseline.EVAL_PATH.unlink()
    report = json.loads((output / "report.json").read_text(encoding="utf-8"))
    assert exit_code == 0 and report["status"] == "ok"
    assert report["total_model_requests"] == 200
    assert report["post_integrity"] == "ok"
    assert report["eval_fixture_removed"] is True
    assert report["preflight"]["test_stub"] is True
    hashes = json.loads((output / "source_hashes_before.json").read_text(encoding="utf-8"))
    assert str(Path("experiments/honest_baseline/plan.json")) in hashes

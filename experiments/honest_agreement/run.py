"""Serial, local-only honest-agreement runner using HadAgent's real scorer.

No downloads or automatic execution. CLI execution requires an explicit flag
and an approval reference; those do not replace the project's P-005 approval.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import asdict
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import socket
import subprocess
import threading
import time
from unittest.mock import patch
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from podl_chain import pdl


SCALE = 10_000
SCHEMA_VERSION = 2
SCORE_DEFINITION = "HadAgent-rule score: case/whitespace-normalized prefix matches; not MMLU accuracy"
CPU_IGPU_SCOPE = "consumer CPU/iGPU"
NVIDIA_GPU_SCOPE = "one consumer NVIDIA GPU"
HARDWARE_SCOPES = (CPU_IGPU_SCOPE, NVIDIA_GPU_SCOPE)
ROOT = Path(__file__).resolve().parents[2]
DIMENSIONS = ("id", "version", "version_output_sha256", "backend", "threads", "batch", "ubatch", "gpu_layers", "parallel", "load_workers")
SOURCE_FILES = ("experiments/honest_agreement/run.py", "experiments/honest_agreement/analyze.py",
                "hadagent/src/podl_chain/pdl.py", "hadagent/src/podl_chain/crypto.py")


class ServerCleanupError(RuntimeError):
    """Do not start another run if stopping the owned process failed."""


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def positive(value, name):
    if type(value) is not int or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def validate_plan(plan: dict) -> None:
    if plan.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported plan schema")
    positive(plan["repeats"], "repeats")
    positive(plan["expected_items"], "expected_items")
    positive(plan["context_size"], "context_size")
    if type(plan["seed"]) is not int or plan["seed"] < 0:
        raise ValueError("seed must be a nonnegative integer")
    if not isinstance(plan["hardware"], dict) or not plan["hardware"]:
        raise ValueError("hardware description is required")
    hardware_scope = plan["hardware"].get("scope")
    if hardware_scope not in HARDWARE_SCOPES:
        raise ValueError("unsupported P-005 hardware scope")
    for name in ("cpu", "gpu", "driver", "ram", "os"):
        if not plan["hardware"].get(name):
            raise ValueError(f"hardware {name} is required")
    if plan["mode"] not in ("reexecution", "same_endpoint_load"):
        raise ValueError("unknown experiment design")
    if plan.get("reference_score_gate", {"minimum_percent_inclusive": 15, "maximum_percent_inclusive": 85}) != {
        "minimum_percent_inclusive": 15, "maximum_percent_inclusive": 85
    }:
        raise ValueError("the preregistered reference gate is fixed at 15..85 percent")
    for name in ("startup_timeout_s", "request_timeout_s", "run_timeout_s", "shutdown_timeout_s", "experiment_timeout_s"):
        positive(plan[name], name)
    for name in ("model", "evalset"):
        if not plan[name].get("path") or not plan[name].get("sha256"):
            raise ValueError(f"{name} path and expected sha256 are required")
    for name in ("source", "license", "selection", "prompt_template"):
        if not plan["evalset"].get(name):
            raise ValueError(f"evalset {name} is required")
    ids, factors, builds, versions = set(), set(), {}, {}
    for config in plan["configurations"]:
        if (not re.fullmatch(r"[A-Za-z0-9_.-]+", config["id"])
                or config["id"] in ids | {"model", "evalset"}):
            raise ValueError("configuration IDs must be unique safe names")
        ids.add(config["id"])
        for name in ("threads", "batch", "ubatch"):
            positive(config[name], name)
        if config["ubatch"] > config["batch"]:
            raise ValueError("ubatch must not exceed batch")
        if type(config["gpu_layers"]) is not int:
            raise ValueError("gpu_layers must be an integer")
        backend = config["backend"]
        device_present = "device" in config
        device = config.get("device")
        if backend == "cpu":
            if config["gpu_layers"] != 0:
                raise ValueError("CPU runs must use zero GPU layers")
            if device_present and device != "none":
                raise ValueError("CPU runs may only omit device or use device 'none'")
        elif backend == "vulkan":
            if config["gpu_layers"] <= 0:
                raise ValueError("Vulkan runs must request positive GPU layers")
        elif backend == "cuda":
            if hardware_scope != NVIDIA_GPU_SCOPE:
                raise ValueError("CUDA runs require the one consumer NVIDIA GPU scope")
            if config["gpu_layers"] <= 0:
                raise ValueError("CUDA runs must request positive GPU layers")
        else:
            raise ValueError("only cpu, vulkan, and cuda backends are in scope")
        if backend in ("vulkan", "cuda"):
            if hardware_scope == NVIDIA_GPU_SCOPE and not device_present:
                raise ValueError("NVIDIA-scope GPU runs require one explicit device")
            prefix = "Vulkan" if backend == "vulkan" else "CUDA"
            if device_present and (not isinstance(device, str)
                                   or not re.fullmatch(rf"{prefix}[0-9]+", device)):
                raise ValueError(f"{backend} device must name one {prefix} device")
        for name in ("binary", "binary_sha256", "version", "version_output_sha256"):
            if not config.get(name):
                raise ValueError(f"configuration {name} is required")
        positive(config["parallel"], "parallel")
        if plan["mode"] == "reexecution":
            if config["parallel"] != 1 or config["load_workers"] != 0:
                raise ValueError("reexecution requires one slot and no load")
        elif (type(config["load_workers"]) is not int or config["load_workers"] != 1
              or config["parallel"] != 2 or not plan.get("load_prompt")):
            raise ValueError("same-endpoint mode requires exactly two slots, one load worker, and a prompt")
        if not isinstance(config.get("runtime_files_sha256"), dict) or not config.get("release_asset_sha256"):
            raise ValueError("release digest and runtime-file manifest are required")
        device_factor = None if backend == "cpu" else config.get("device")
        factor = tuple(config[k] for k in DIMENSIONS if k not in ("id", "version", "version_output_sha256")) + (
            device_factor, config["binary_sha256"])
        if factor in factors:
            raise ValueError("duplicate configuration factors would overweight a cell")
        factors.add(factor)
        build = (config["version"], config["backend"])
        identity = (config["binary_sha256"], config["version_output_sha256"],
                    canonical(config["runtime_files_sha256"]), config["release_asset_sha256"])
        if build in builds and builds[build] != identity:
            raise ValueError("one version/backend label must identify one binary/version output")
        builds[build] = identity
        if config["binary_sha256"] in versions and versions[config["binary_sha256"]] != config["version"]:
            raise ValueError("one binary cannot represent different version labels")
        versions[config["binary_sha256"]] = config["version"]
    if plan["mode"] == "same_endpoint_load" and len(ids) != 1:
        raise ValueError("same-endpoint plan must have exactly one configuration")
    if not ids or plan["reference_run_id"] != planned_runs(plan)[0]:
        raise ValueError("reference_run_id must identify the first planned run")


def planned_runs(plan):
    phases = ("idle", "loaded") if plan["mode"] == "same_endpoint_load" else ("single",)
    return [run_id(c, r, phase) for c in plan["configurations"]
            for r in range(plan["repeats"]) for phase in phases]


def run_id(config, repeat, phase):
    base = f"{config['id']}/repeat-{repeat}"
    return base if phase == "single" else f"{base}/{phase}"


def source_hashes():
    return {name: digest((ROOT / name).read_bytes()) for name in SOURCE_FILES}


def reference_stop(plan, row):
    if row["run_id"] != plan["reference_run_id"]:
        return None
    if row["status"] != "ok":
        return "reference failed"
    result = row["result"]
    if not 15 * result["total"] <= 100 * result["correct"] <= 85 * result["total"]:
        return "reference HadAgent-rule score outside preregistered 15..85 percent range"
    if row.get("calibration_only"):
        return "calibration only; preregister this reference score before the matrix"
    if result["correct"] != plan["preregistered_reference_correct"]:
        return "reference differs from preregistered calibration score; do not replace it"
    return None


def checked_artifact(path, expected_hash):
    path = Path(path).resolve()
    if path.name.lower() == ".env":
        raise ValueError(".env is not an experiment artifact")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", expected_hash):
        raise ValueError("replace placeholder checksums before execution")
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    if hasher.hexdigest() != expected_hash.lower():
        raise ValueError(f"artifact checksum mismatch: {path.name}")
    return str(path), hasher.hexdigest()


def checked_runtime(config, binary):
    base = Path(binary).resolve().parent
    expected = config["runtime_files_sha256"]
    pinned = set()
    for name, checksum in expected.items():
        path = (base / name).resolve()
        if Path(name).is_absolute() or not path.is_relative_to(base):
            raise ValueError("runtime files must be inside this release directory")
        checked_artifact(path, checksum)
        pinned.add(path)
    bundled_dlls = {p.resolve() for p in base.rglob("*") if p.is_file() and p.suffix.lower() == ".dll"}
    if not bundled_dlls.issubset(pinned):
        raise ValueError("release contains an unpinned runtime DLL")


def checked_session_integrity(config, artifacts, sources):
    for key in ("model", "evalset", config["id"]):
        checked_artifact(*artifacts[key])
    checked_runtime(config, artifacts[config["id"]][0])
    if source_hashes() != sources:
        raise RuntimeError("experiment sources changed during execution")


def process_options():
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


def code_commit():
    provenance_path = ROOT / "bundle-provenance.json"
    if provenance_path.exists():
        try:
            provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ValueError("invalid bundle provenance") from error
        commit = provenance.get("source_commit") if isinstance(provenance, dict) else None
        recorded_sources = provenance.get("source_files_sha256") if isinstance(provenance, dict) else None
        if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-fA-F]{40}", commit):
            raise ValueError("bundle provenance requires a 40-hex source commit")
        if recorded_sources != source_hashes():
            raise ValueError("bundle provenance source hashes do not match current sources")
        return commit.lower()
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True,
        text=True, timeout=10, **process_options(),
    ).stdout.strip()
    if not re.fullmatch(r"[0-9a-fA-F]{40}", commit):
        raise RuntimeError("git did not report a 40-hex source commit")
    return commit.lower()


def read_version(binary):
    result = subprocess.run(
        [binary, "--version"], cwd=Path(binary).parent, check=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        timeout=15, **process_options(),
    )
    if not result.stdout.strip():
        raise ValueError("binary did not report a version")
    return result.stdout.strip()


def choose_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def command_for(plan, config, binary, model, port):
    # No arbitrary extra flags: the caller cannot override binding or model.
    command = [binary, "--model", model, "--host", "127.0.0.1", "--port", str(port),
               "--threads", str(config["threads"]), "--threads-batch", str(config["threads"]),
               "--batch-size", str(config["batch"]), "--ubatch-size", str(config["ubatch"]),
               "--n-gpu-layers", str(config["gpu_layers"]), "--ctx-size", str(plan["context_size"]),
               "--parallel", str(config["parallel"]), "--seed", str(plan["seed"])]
    if "device" in config:
        command.extend(["--device", config["device"]])
    return command


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError("local server redirects are forbidden")


class LoopbackTransport:
    def __init__(self, port, request_timeout, deadline):
        self.port = port
        self.request_timeout = request_timeout
        self.deadline = deadline
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def open(self, request, timeout=120):
        url = request if isinstance(request, str) else request.full_url
        parsed = urlsplit(url)
        if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1"
                or parsed.port != self.port or parsed.username or parsed.password
                or parsed.path not in ("/health", "/completion") or parsed.query or parsed.fragment):
            raise ValueError("only this run's loopback health/completion URLs are allowed")
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("run deadline exceeded")
        return self.opener.open(request, timeout=min(timeout, self.request_timeout, remaining))


def wait_for_health(process, transport, health_url, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("llama-server exited before becoming healthy")
        try:
            with transport.open(health_url, timeout=min(1, deadline - time.monotonic())) as response:
                ready = json.loads(response.read()).get("status") == "ok"
            if ready and process.poll() is None:
                return
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            pass
        time.sleep(0.1)
    raise TimeoutError("llama-server health timeout")


@contextmanager
def owned_server(command, log_path, shutdown_timeout):
    with log_path.open("xb") as log:
        process = subprocess.Popen(
            command, cwd=Path(command[0]).parent, stdin=subprocess.DEVNULL,
            stdout=log, stderr=subprocess.STDOUT, shell=False, **process_options(),
        )
        try:
            yield process
        finally:
            try:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=shutdown_timeout)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=shutdown_timeout)
            except Exception as error:
                raise ServerCleanupError("could not confirm owned server shutdown") from error


@contextmanager
def server_deadline(process, deadline, shutdown_timeout):
    """Terminate inference even if a response trickles past socket timeouts."""
    expired, errors = threading.Event(), []

    def expire():
        expired.set()
        try:
            if process.poll() is None:
                process.kill()
        except Exception as error:
            errors.append(str(error))

    timer = threading.Timer(max(0, deadline - time.monotonic()), expire)
    timer.daemon = True
    timer.start()
    try:
        yield
        if expired.is_set():
            raise TimeoutError("server execution deadline exceeded")
    finally:
        timer.cancel()
        timer.join(shutdown_timeout)
        if timer.is_alive() or errors:
            raise ServerCleanupError("deadline watchdog could not confirm termination")


class BackgroundLoad:
    """Benign, fixed requests to the same owned endpoint; never a second server."""

    def __init__(self, count, completion, endpoint, prompt, cfg, join_timeout):
        self.stop = threading.Event()
        self.started = threading.Event()
        self.intervals = []
        self.errors = []
        self.join_timeout = join_timeout

        def worker():
            while not self.stop.is_set():
                start = time.monotonic()
                self.started.set()
                try:
                    completion(endpoint, prompt, cfg)
                    self.intervals.append((start, time.monotonic()))
                except Exception as error:
                    self.errors.append(f"{type(error).__name__}: {error}")
                    return

        self.threads = [threading.Thread(target=worker, daemon=True) for _ in range(count)]

    def __enter__(self):
        for thread in self.threads:
            thread.start()
        if self.threads and not self.started.wait(self.join_timeout):
            self.stop.set()
            raise RuntimeError("background load did not start")
        return self

    def __exit__(self, *exc):
        self.stop.set()
        deadline = time.monotonic() + self.join_timeout
        for thread in self.threads:
            thread.join(max(0, deadline - time.monotonic()))
        if any(thread.is_alive() for thread in self.threads):
            raise ServerCleanupError("background worker did not stop; abort matrix")


def make_row(plan, config, repeat, phase, artifacts, label, approval_note, commit, sources):
    cfg = pdl.DecodeConfig()
    return {
        "schema_version": SCHEMA_VERSION, "evidence_label": label, "mode": plan["mode"],
        "score_definition": SCORE_DEFINITION,
        "run_id": run_id(config, repeat, phase), "reference_run_id": plan["reference_run_id"],
        "planned_run_ids": planned_runs(plan), "plan_sha256": digest(canonical(plan).encode()),
        "code_commit": commit, "code_sources_sha256": sources, "approval_note": approval_note,
        "config": {**{k: config[k] for k in DIMENSIONS},
                   **({"device": config["device"]} if "device" in config else {}),
                   "repeat": repeat, "phase": phase},
        "context_size": plan["context_size"], "seed": plan["seed"],
        "hardware": plan["hardware"], "platform": platform.platform(),
        "artifacts": {"model_sha256": artifacts["model"][1],
                      "evalset_sha256": artifacts["evalset"][1],
                      "binary_sha256": artifacts[config["id"]][1]},
        "release_asset_sha256": config["release_asset_sha256"],
        "runtime_files_sha256": config["runtime_files_sha256"],
        "evalset_provenance": {k: plan["evalset"][k] for k in ("source", "license", "selection", "prompt_template")},
        "decode_config": {**asdict(cfg), "sha256": cfg.hash().hex()},
        "status": "failed", "result": None, "error": None, "reported_version": None,
        "command": None, "server_pid": None, "stop_reason": None,
        "calibration_only": False,
        "post_run_integrity": {"status": "pending", "error": None},
        "backend_effective": "UNVERIFIED (inspect server log before interpretation)",
        "load": None, "timing_s": {"startup": None, "scoring": None, "session_total": None},
    }


def score_phase(plan, config, row, pairs, endpoint, process, transport):
    cfg, outputs, request_intervals = pdl.DecodeConfig(), [], []
    original_completion = pdl.llama_cpp_completion

    def capture(url, prompt, decode_cfg):
        if process.poll() is not None:
            raise RuntimeError("llama-server exited during scoring")
        index = len(outputs)
        if index >= len(pairs) or prompt != pairs[index][0] or url != endpoint or decode_cfg != cfg:
            raise RuntimeError("unexpected scorer request sequence/configuration")
        before = time.monotonic()
        text = original_completion(url, prompt, decode_cfg)
        request_intervals.append((before, time.monotonic()))
        normalized = pdl.normalize_answer(text)
        outputs.append({"item_index": index, "prompt_sha256": digest(prompt.encode()),
                        "raw_output_sha256": digest(text.encode()),
                        "normalized_output_sha256": digest(normalized.encode()),
                        "bare_answer_letter": normalized in ("a", "b", "c", "d"),
                        "matched": normalized.startswith(pdl.normalize_answer(pairs[index][1]))})
        return text

    count = config["load_workers"] if row["config"]["phase"] == "loaded" else 0
    load = BackgroundLoad(count, original_completion, endpoint, plan.get("load_prompt", ""),
                          cfg, plan["request_timeout_s"] + plan["shutdown_timeout_s"])
    scoring = time.monotonic()
    try:
        # Background calls retain the original function; only audit calls are captured.
        with patch.object(pdl.urllib.request, "urlopen", transport.open), \
                patch.object(pdl, "llama_cpp_completion", capture), load:
            correct = pdl.score_exact_match(endpoint, pairs, cfg)
        overlap = sum(any(a < d and c < b for c, d in load.intervals)
                      for a, b in request_intervals)
        row["load"] = {"workers": count, "completed_requests": len(load.intervals),
                       "errors": load.errors, "audit_requests_with_client_overlap": overlap}
        if count and (load.errors or overlap != len(pairs)):
            raise RuntimeError("concurrent-load condition failed: require successful overlapping requests for every audit")
        if len(outputs) != len(pairs) or sum(o["matched"] for o in outputs) != correct:
            raise RuntimeError("captured outputs disagree with HadAgent scoring")
        row["result"] = {"correct": correct, "total": len(pairs), "score_scale": SCALE,
                         "score_scaled": correct * SCALE // len(pairs), "outputs": outputs}
        row["status"] = "ok"
    except (Exception, KeyboardInterrupt) as error:
        row["error"] = {"stage": "scoring", "type": type(error).__name__, "message": str(error),
                        "completed_items": len(outputs)}
        row["status"] = "interrupted" if isinstance(error, KeyboardInterrupt) else "failed"
        row["load"] = {"workers": count, "completed_requests": len(load.intervals), "errors": load.errors}
        raise
    finally:
        row["timing_s"]["scoring"] = time.monotonic() - scoring


def measure_session(plan, config, repeat, artifacts, pairs, log_dir, label, approval_note,
                    commit, sources, deadline, calibration_only=False):
    phases = ("idle", "loaded") if plan["mode"] == "same_endpoint_load" else ("single",)
    row = make_row(plan, config, repeat, phases[0], artifacts, label, approval_note, commit, sources)
    row["calibration_only"] = calibration_only
    rows = [row]
    started = time.monotonic()
    log_path = log_dir / f"{config['id']}-repeat-{repeat}.log"
    stage = "integrity"
    integrity_stop = None
    try:
        checked_session_integrity(config, artifacts, sources)
        if time.monotonic() >= deadline:
            raise TimeoutError("experiment deadline exceeded")
        stage = "version"
        binary = artifacts[config["id"]][0]
        version = read_version(binary)
        row["reported_version"] = version
        if digest(version.encode()) != config["version_output_sha256"]:
            raise ValueError("reported version differs from pinned version output")
        stage = "startup"
        port = choose_port()
        endpoint = f"http://127.0.0.1:{port}/completion"
        command = command_for(plan, config, binary, artifacts["model"][0], port)
        row["command"] = command
        transport = LoopbackTransport(port, plan["request_timeout_s"], min(deadline, started + plan["run_timeout_s"]))
        with owned_server(command, log_path, plan["shutdown_timeout_s"]) as process, \
                server_deadline(process, transport.deadline, plan["shutdown_timeout_s"]):
            row["server_pid"] = process.pid
            startup = time.monotonic()
            wait_for_health(process, transport, f"http://127.0.0.1:{port}/health",
                            min(plan["startup_timeout_s"], transport.deadline - startup))
            row["timing_s"]["startup"] = time.monotonic() - startup
            for index, phase in enumerate(phases):
                if index:
                    row = make_row(plan, config, repeat, phase, artifacts, label, approval_note, commit, sources)
                    row.update(reported_version=version, command=command, server_pid=process.pid)
                    rows.append(row)
                stage = "scoring"
                score_phase(plan, config, row, pairs, endpoint, process, transport)
                row["stop_reason"] = reference_stop(plan, row)
                if row["stop_reason"]:
                    break
            stage = "shutdown"
    except (Exception, KeyboardInterrupt) as error:
        # A cleanup failure invalidates every phase in that session.
        affected = rows if stage == "shutdown" or isinstance(error, ServerCleanupError) else [row]
        for affected_row in affected:
            affected_row["status"] = "interrupted" if isinstance(error, KeyboardInterrupt) else "failed"
            affected_row["result"] = None
            if not affected_row["error"] or isinstance(error, ServerCleanupError):
                affected_row["error"] = {"stage": stage, "type": type(error).__name__, "message": str(error),
                                         "completed_items": 0}
    finally:
        try:
            checked_session_integrity(config, artifacts, sources)
        except (Exception, KeyboardInterrupt) as error:
            integrity_error = {"type": type(error).__name__, "message": str(error)}
            integrity_stop = "post-run integrity check failed; abort matrix"
            for item in rows:
                completed_items = item["result"]["total"] if item["result"] else 0
                item["post_run_integrity"] = {"status": "failed", "error": dict(integrity_error)}
                item["result"] = None
                if item["status"] == "ok":
                    item["status"] = "failed"
                if item["error"] is None:
                    item["error"] = {"stage": "integrity_after_run", **integrity_error,
                                     "completed_items": completed_items}
        else:
            for item in rows:
                item["post_run_integrity"] = {"status": "ok", "error": None}
        for item in rows:
            item["timing_s"]["session_total"] = time.monotonic() - started
            item["server_log"] = str(log_path)
            item["server_log_sha256"] = digest(log_path.read_bytes()) if log_path.exists() else None
            item["stop_reason"] = integrity_stop or reference_stop(plan, item)
    return rows


def run_experiment(plan, output_path, *, approval_note, evidence_label="MEASURED", calibration_only=False,
                   external_deadline=None):
    validate_plan(plan)
    if not approval_note or evidence_label not in ("MEASURED", "SIMULATED"):
        raise ValueError("approval reference and explicit evidence label are required")
    calibration = plan.get("preregistered_reference_correct")
    if not calibration_only and (type(calibration) is not int or not 0 <= calibration <= plan["expected_items"]):
        raise ValueError("preregistered calibration score is required before matrix execution")
    if evidence_label == "MEASURED" and plan["expected_items"] != 100:
        raise ValueError("P-005 measured plan requires the preregistered 100-item subset")
    if evidence_label == "MEASURED" and "UNRESOLVED" in canonical(plan).upper():
        raise ValueError("resolve artifact, license, and hardware placeholders before measured execution")
    started = time.monotonic()
    if external_deadline is not None:
        if (isinstance(external_deadline, bool) or not isinstance(external_deadline, (int, float))
                or not math.isfinite(external_deadline)):
            raise ValueError("external_deadline must be a finite monotonic timestamp")
        if external_deadline <= started:
            raise TimeoutError("external study deadline already passed")
    deadline = started + plan["experiment_timeout_s"]
    if external_deadline is not None:
        deadline = min(deadline, external_deadline)
    artifacts = {name: checked_artifact(plan[name]["path"], plan[name]["sha256"])
                 for name in ("model", "evalset")}
    for config in plan["configurations"]:
        if not re.fullmatch(r"[0-9a-f]{64}", config["version_output_sha256"]):
            raise ValueError("replace version-output checksum placeholder before execution")
        if not re.fullmatch(r"[0-9a-f]{64}", config["release_asset_sha256"]):
            raise ValueError("record publisher-verified release archive checksum before execution")
        artifacts[config["id"]] = checked_artifact(config["binary"], config["binary_sha256"])
        checked_runtime(config, artifacts[config["id"]][0])
    eval_bytes = Path(artifacts["evalset"][0]).read_bytes()
    if digest(eval_bytes) != artifacts["evalset"][1]:
        raise ValueError("evalset changed during preparation")
    pairs = pdl.parse_evalset_jsonl(eval_bytes)
    if len(pairs) != plan["expected_items"] or any(
        not isinstance(p, str) or not isinstance(a, str) or not p.strip() or not a.strip()
        for p, a in pairs
    ):
        raise ValueError("evalset size or prompt/answer content is invalid")
    output_path = Path(output_path).resolve()
    if output_path.suffix != ".jsonl":
        raise ValueError("output must be a new .jsonl file")
    log_dir = output_path.parent / f"{output_path.stem}-logs"
    commit, sources = code_commit(), source_hashes()
    log_dir.mkdir(parents=True, exist_ok=False)
    rows = []
    with output_path.open("x", encoding="utf-8") as output:
        for config in plan["configurations"]:
            for repeat in range(plan["repeats"]):
                if rows and time.monotonic() >= deadline:
                    return rows
                session = measure_session(plan, config, repeat, artifacts, pairs, log_dir,
                                          evidence_label, approval_note, commit, sources, deadline, calibration_only)
                for row in session:
                    output.write(canonical(row) + "\n")
                    output.flush()
                    rows.append(row)
                if any(row["stop_reason"] or row["status"] == "interrupted" or (
                    row["error"] and row["error"]["type"] == "ServerCleanupError"
                ) for row in session):
                    return rows
    return rows

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--execute", action="store_true", help="run only after P-005 RED approval")
    parser.add_argument("--calibrate", action="store_true", help="with --execute: score only the frozen reference, no matrix")
    parser.add_argument("--approval-note", help="reference to the recorded approval; not an approval itself")
    args = parser.parse_args(argv)
    plan = json.loads(args.config.read_text(encoding="utf-8"))
    validate_plan(plan)
    if not args.execute:
        print(json.dumps({"mode": "PLAN ONLY", "planned_run_ids": planned_runs(plan),
                          "reference_run_id": plan["reference_run_id"],
                          "warning": "No artifacts, hashes, versions, or backend have been verified."}, indent=2))
        return 0
    if not args.output or not args.approval_note:
        parser.error("--execute requires --output and --approval-note")
    rows = run_experiment(plan, args.output, approval_note=args.approval_note, calibration_only=args.calibrate)
    if args.calibrate:
        return 0 if len(rows) == 1 and rows[0]["status"] == "ok" and rows[0]["stop_reason"].startswith("calibration only") else 1
    return 0 if len(rows) == len(planned_runs(plan)) and all(
        row["status"] == "ok" and not row["stop_reason"] for row in rows
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())

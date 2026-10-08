"""Offline tests for the P-008 artifact preparation boundary."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import stat
import subprocess
import zipfile

import pytest

from experiments.honest_agreement.desktop import prepare_artifacts as artifacts


ANCHOR = "a" * 64


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def make_zip(entries: list[tuple[str, bytes, int | None]]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, content, unix_mode in entries:
            info = zipfile.ZipInfo(name)
            if unix_mode is not None:
                info.create_system = 3
                info.external_attr = unix_mode << 16
            archive.writestr(info, content)
    return output.getvalue()


def build_archive(version: str, backend: str) -> bytes:
    return make_zip([
        ("llama-server.exe", f"server:{version}:{backend}".encode(), stat.S_IFREG | 0o755),
        ("common.dll", f"common:{version}:{backend}".encode(), stat.S_IFREG | 0o644),
        (f"{backend}.dll", f"backend:{version}:{backend}".encode(), stat.S_IFREG | 0o644),
        ("README.txt", b"fixture data only", stat.S_IFREG | 0o644),
    ])


def runtime_archive(version: str) -> bytes:
    return make_zip([
        ("cudart64_12.dll", f"cudart:{version}".encode(), stat.S_IFREG | 0o644),
    ])


def fixture_payloads() -> dict[tuple[str | None, str], bytes]:
    values: dict[tuple[str | None, str], bytes] = {}
    for version in ("b11513", "b11514"):
        for backend, variant in (
            ("cpu", "cpu"),
            ("vulkan", "vulkan"),
            ("cuda", "cuda-12.4"),
        ):
            name = f"llama-{version}-bin-win-{variant}-x64.zip"
            values[(version, name)] = build_archive(version, backend)
        name = "cudart-llama-bin-win-cuda-12.4-x64.zip"
        values[(version, name)] = runtime_archive(version)
    values[(None, artifacts.MODEL_NAME)] = b"synthetic fp16 model"
    return values


def official_url(version: str | None, name: str) -> str:
    if version is not None:
        return f"https://github.com/ggml-org/llama.cpp/releases/download/{version}/{name}"
    return (
        "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/"
        "91cad51170dc346986eccefdc2dd33a9da36ead9/" + name
    )


def make_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    payloads: dict[tuple[str | None, str], bytes] | None = None,
    install_downloads: bool = True,
) -> tuple[Path, dict[tuple[str | None, str], bytes]]:
    payloads = fixture_payloads() if payloads is None else payloads
    root = tmp_path / "bundle"
    root.mkdir()
    (root / "bundle-manifest.json").write_text("{}\n", encoding="utf-8")
    state = root / "state"
    state.mkdir()
    authorization = {
        "p008_record": "P-008 approved",
        "p005b_record": "P-005b approved",
        "matthew_out_of_band_record": "recorded outside the bundle UI",
        "offline_bundle_review_record": "reviewed hash record",
        "runtime_review_record": "SIMULATED reviewed runtime",
        "desktop_specs_confirmed": True,
        "notes": "This notes field is not treated as approval.",
    }
    # Match the Windows PowerShell Set-Content -Encoding UTF8 behavior.
    (state / "authorization.json").write_text(
        json.dumps(authorization), encoding="utf-8-sig"
    )
    frozen: dict[tuple[str | None, str], dict[str, object]] = {}
    records = []
    for (version, name), content in payloads.items():
        record = {
            "name": name,
            "url": official_url(version, name),
            "sha256": digest(content),
            "bytes": len(content),
            "publisher": "synthetic publisher metadata",
        }
        if version is not None:
            record["version"] = version
        records.append(record)
        frozen[(version, name)] = {
            "url": record["url"],
            "sha256": record["sha256"],
            "bytes": record["bytes"],
        }
        if install_downloads:
            destination = root / "downloads" / (version or "model") / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
    (root / "downloads.lock.json").write_text(
        json.dumps({"artifacts": records}, sort_keys=True), encoding="utf-8"
    )
    monkeypatch.setattr(artifacts, "OFFICIAL_ARTIFACTS", frozen)
    monkeypatch.setattr(
        artifacts.verify_bundle,
        "verify",
        lambda verified_root, manifest, anchor: {"status": "verified"}
        if anchor == ANCHOR
        else (_ for _ in ()).throw(artifacts.verify_bundle.VerificationError("bad anchor")),
    )
    return root, payloads


class FakeResponse:
    def __init__(self, url: str, content: bytes):
        self.status = 200
        self._url = url
        self._stream = io.BytesIO(content)
        self.headers = {"Content-Length": str(len(content))}

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def geturl(self) -> str:
        return self._url

    def read(self, size: int) -> bytes:
        return self._stream.read(size)


class FakeOpener:
    def __init__(self, by_url: dict[str, bytes]):
        self.by_url = by_url
        self.requests = []

    def open(self, request, timeout):
        self.requests.append((request, timeout))
        assert request.get_method() == "GET"
        assert timeout == artifacts.NETWORK_TIMEOUT_SECONDS
        return FakeResponse(request.full_url, self.by_url[request.full_url])


def test_authorization_is_required_before_network(tmp_path, monkeypatch):
    root, _ = make_fixture(tmp_path, monkeypatch, install_downloads=False)
    authorization_path = root / "state" / "authorization.json"
    value = json.loads(authorization_path.read_text(encoding="utf-8-sig"))
    value.pop("offline_bundle_review_record")
    authorization_path.write_text(json.dumps(value), encoding="utf-8-sig")
    monkeypatch.setattr(
        artifacts,
        "_network_opener",
        lambda: (_ for _ in ()).throw(AssertionError("network must remain untouched")),
    )
    with pytest.raises(artifacts.ArtifactError, match="offline_bundle_review_record"):
        artifacts.fetch(root, ANCHOR)


def test_fetch_is_get_only_digest_checked_and_resumable(tmp_path, monkeypatch):
    root, payloads = make_fixture(tmp_path, monkeypatch, install_downloads=False)
    by_url = {official_url(version, name): content for (version, name), content in payloads.items()}
    opener = FakeOpener(by_url)
    monkeypatch.setattr(artifacts, "_assert_public_host", lambda host: None)
    monkeypatch.setattr(artifacts, "_network_opener", lambda: opener)

    result = artifacts.fetch(root, ANCHOR)
    assert len(result["artifacts"]) == len(payloads)
    assert all(item["status"] == "downloaded" for item in result["artifacts"])
    assert len(opener.requests) == len(payloads)
    assert (root / "downloads" / "model" / artifacts.MODEL_NAME).read_bytes() == payloads[
        (None, artifacts.MODEL_NAME)
    ]

    monkeypatch.setattr(
        artifacts,
        "_network_opener",
        lambda: (_ for _ in ()).throw(AssertionError("verified downloads must not be fetched again")),
    )
    resumed = artifacts.fetch(root, ANCHOR)
    assert all(item["status"] == "already_verified" for item in resumed["artifacts"])


def test_fetch_removes_a_failed_integrity_download(tmp_path, monkeypatch):
    root, payloads = make_fixture(tmp_path, monkeypatch, install_downloads=False)
    by_url = {official_url(version, name): content for (version, name), content in payloads.items()}
    corrupt_key = sorted(payloads, key=lambda item: ((item[0] or "model"), item[1]))[0]
    corrupt_url = official_url(*corrupt_key)
    original = by_url[corrupt_url]
    by_url[corrupt_url] = bytes([original[0] ^ 1]) + original[1:]
    monkeypatch.setattr(artifacts, "_assert_public_host", lambda host: None)
    monkeypatch.setattr(artifacts, "_network_opener", lambda: FakeOpener(by_url))

    with pytest.raises(artifacts.ArtifactError, match="integrity check"):
        artifacts.fetch(root, ANCHOR)
    destination = root / "downloads" / (corrupt_key[0] or "model") / corrupt_key[1]
    assert not destination.exists()


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/ggml-org/llama.cpp/releases/download/b1/a.zip",
        "https://127.0.0.1/a.zip",
        "https://user:password@github.com/a.zip",
        "https://github.com:444/a.zip",
    ],
)
def test_network_url_boundary_rejects_downgrades_internal_and_credentials(url):
    with pytest.raises(artifacts.ArtifactError, match="allowlist"):
        artifacts._validate_url(url, initial=False, resolve=False)


def test_extract_merges_corresponding_cuda_runtime_without_overwrite(tmp_path, monkeypatch):
    root, _ = make_fixture(tmp_path, monkeypatch)
    result = artifacts.extract(root, ANCHOR)
    assert {(item["version"], item["backend"]) for item in result["builds"]} == artifacts.EXPECTED_BUILDS
    for version in ("b11513", "b11514"):
        cuda = root / "downloads" / "extracted" / version / "cuda"
        assert (cuda / "llama-server.exe").is_file()
        assert (cuda / "cudart64_12.dll").read_bytes() == f"cudart:{version}".encode()
    with pytest.raises(artifacts.ArtifactError, match="overwrite extracted build"):
        artifacts.extract(root, ANCHOR)


def test_extract_rejects_traversal_before_writing_any_build(tmp_path, monkeypatch):
    payloads = fixture_payloads()
    key = ("b11513", "llama-b11513-bin-win-cpu-x64.zip")
    payloads[key] = make_zip([
        ("llama-server.exe", b"server", stat.S_IFREG | 0o755),
        ("../escape.dll", b"escape", stat.S_IFREG | 0o644),
    ])
    root, _ = make_fixture(tmp_path, monkeypatch, payloads=payloads)
    with pytest.raises(artifacts.ArtifactError, match="traversal"):
        artifacts.extract(root, ANCHOR)
    assert not (root / "escape.dll").exists()
    assert not (root / "downloads" / "extracted").exists()


def test_extract_rejects_zip_symlinks_and_case_collisions(tmp_path, monkeypatch):
    payloads = fixture_payloads()
    key = ("b11513", "llama-b11513-bin-win-cpu-x64.zip")
    payloads[key] = make_zip([
        ("llama-server.exe", b"server", stat.S_IFREG | 0o755),
        ("link.dll", b"target.dll", stat.S_IFLNK | 0o777),
    ])
    root, _ = make_fixture(tmp_path, monkeypatch, payloads=payloads)
    with pytest.raises(artifacts.ArtifactError, match="symlink"):
        artifacts.extract(root, ANCHOR)

    other_tmp = tmp_path / "case"
    other_tmp.mkdir()
    payloads = fixture_payloads()
    payloads[key] = make_zip([
        ("llama-server.exe", b"server", stat.S_IFREG | 0o755),
        ("Lib/A.dll", b"one", stat.S_IFREG | 0o644),
        ("lib/a.DLL", b"two", stat.S_IFREG | 0o644),
    ])
    root, _ = make_fixture(other_tmp, monkeypatch, payloads=payloads)
    with pytest.raises(artifacts.ArtifactError, match="case-colliding"):
        artifacts.extract(root, ANCHOR)


def test_extract_authenticates_every_archive_before_central_directory_use(tmp_path, monkeypatch):
    root, _ = make_fixture(tmp_path, monkeypatch)
    archive = root / "downloads" / "b11514" / "llama-b11514-bin-win-vulkan-x64.zip"
    corrupted = bytearray(archive.read_bytes())
    corrupted[-1] ^= 1
    archive.write_bytes(corrupted)
    monkeypatch.setattr(
        artifacts,
        "_read_zip_members",
        lambda path: (_ for _ in ()).throw(AssertionError("ZIP parsing must wait for all archive hashes")),
    )
    with pytest.raises(artifacts.ArtifactError, match="publisher SHA-256 mismatch"):
        artifacts.extract(root, ANCHOR)
    assert not (root / "downloads" / "extracted").exists()


def inspection_process(calls):
    def fake_run(command, **options):
        calls.append((command, options))
        assert command[1] in ("--version", "--help", "--list-devices")
        assert options["shell"] is False
        assert options["stdin"] is subprocess.DEVNULL
        assert options["stderr"] is subprocess.STDOUT
        if artifacts.os.name == "nt":
            assert options["creationflags"] == subprocess.CREATE_NO_WINDOW
        backend = Path(options["cwd"]).name
        version = Path(options["cwd"]).parent.name
        if command[1] == "--version":
            output = f"llama.cpp {version}\r\n"
        elif command[1] == "--help":
            output = "usage: " + " ".join(artifacts.REQUIRED_SERVER_FLAGS) + "\n"
        elif backend == "cuda":
            output = "Available devices:\n  CUDA0: NVIDIA GeForce RTX 3060 (12288 MiB)\n"
        elif backend == "vulkan":
            output = "Available devices:\n  Vulkan0: NVIDIA GeForce RTX 3060 (12288 MiB)\n"
        else:
            output = "Available devices: none\n"
        return subprocess.CompletedProcess(command, 0, stdout=output)

    return fake_run


def test_inspect_hashes_all_runtime_files_and_pins_exact_gpu(tmp_path, monkeypatch):
    root, _ = make_fixture(tmp_path, monkeypatch)
    artifacts.extract(root, ANCHOR)
    calls = []
    monkeypatch.setattr(artifacts.subprocess, "run", inspection_process(calls))

    result = artifacts.inspect(root, ANCHOR)
    assert result["status"] == "verified"
    assert len(result["builds"]) == 6
    assert len(calls) == 18
    for build in result["builds"]:
        assert not Path(build["binary"]).is_absolute()
        assert build["binary_sha256"] == build["runtime_files_sha256"]["llama-server.exe"]
        assert all(name.lower().endswith((".exe", ".dll")) for name in build["runtime_files_sha256"])
        if build["backend"] == "cpu":
            assert "device" not in build
        else:
            expected = "CUDA0" if build["backend"] == "cuda" else "Vulkan0"
            assert build["device"] == expected
            assert build["device_listing"]["devices"] == [{
                "id": expected,
                "description": "NVIDIA GeForce RTX 3060 (12288 MiB)",
            }]
    assert json.loads((root / "state" / "builds.json").read_text(encoding="utf-8")) == result

    with pytest.raises(artifacts.ArtifactError, match="overwrite state/builds.json"):
        artifacts.inspect(root, ANCHOR)
    assert len(calls) == 18


def test_inspect_never_executes_when_extracted_integrity_fails(tmp_path, monkeypatch):
    root, _ = make_fixture(tmp_path, monkeypatch)
    artifacts.extract(root, ANCHOR)
    binary = root / "downloads" / "extracted" / "b11513" / "cpu" / "llama-server.exe"
    binary.write_bytes(b"tampered")
    monkeypatch.setattr(
        artifacts.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unverified EXE must never run")),
    )
    with pytest.raises(artifacts.ArtifactError, match="differs from verified archive"):
        artifacts.inspect(root, ANCHOR)
    assert not (root / "state" / "builds.json").exists()


def test_inspect_rejects_ambiguous_rtx_3060_device_listing(tmp_path, monkeypatch):
    root, _ = make_fixture(tmp_path, monkeypatch)
    artifacts.extract(root, ANCHOR)
    calls = []
    normal = inspection_process(calls)

    def duplicate_gpu(command, **options):
        result = normal(command, **options)
        if command[1] == "--list-devices" and Path(options["cwd"]).name == "cuda":
            result.stdout = (
                "Available devices:\n"
                "  CUDA0: NVIDIA GeForce RTX 3060 (12288 MiB)\n"
                "  CUDA1: NVIDIA GeForce RTX 3060 (12288 MiB)\n"
            )
        return result

    monkeypatch.setattr(artifacts.subprocess, "run", duplicate_gpu)
    with pytest.raises(artifacts.ArtifactError, match="exactly one NVIDIA GeForce RTX 3060"):
        artifacts.inspect(root, ANCHOR)
    assert not (root / "state" / "builds.json").exists()

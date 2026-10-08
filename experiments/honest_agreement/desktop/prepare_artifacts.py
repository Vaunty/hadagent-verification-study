#!/usr/bin/env python3
"""Fetch, safely extract, and inspect the pinned P-008 runtime artifacts.

Every command authenticates the immutable bundle first.  The mutable
authorization record is only a fail-closed execution gate; it is not itself a
source of approval.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import ipaddress
import json
import os
from pathlib import Path
from pathlib import PurePosixPath
import re
import socket
import stat
import subprocess
import sys
from typing import Any
import urllib.error
import urllib.parse
import urllib.request
import zipfile


# ``python -I`` intentionally removes the script directory from sys.path.
SCRIPT_DIRECTORY = Path(__file__).resolve().parent
if os.fspath(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, os.fspath(SCRIPT_DIRECTORY))
import verify_bundle  # noqa: E402  (must follow the isolated-mode path fix)


HASH_RE = re.compile(r"[0-9a-fA-F]{64}\Z")
BUILD_RE = re.compile(
    r"llama-(b1151[34])-bin-win-(cpu|vulkan|cuda-12\.4)-x64\.zip\Z"
)
CUDART_RE = re.compile(r"cudart-llama-bin-win-cuda-12\.4-x64\.zip\Z")
MODEL_NAME = "qwen2.5-1.5b-instruct-fp16.gguf"
EXPECTED_GPU_NAME = "NVIDIA GeForce RTX 3060"
EXPECTED_BUILDS = {
    (version, backend)
    for version in ("b11513", "b11514")
    for backend in ("cpu", "vulkan", "cuda")
}
ALLOWED_NETWORK_HOSTS = frozenset({
    "github.com",
    "release-assets.githubusercontent.com",
    "huggingface.co",
    "cas-bridge.xethub.hf.co",
    "cdn-lfs.huggingface.co",
})
INITIAL_NETWORK_HOSTS = frozenset({"github.com", "huggingface.co"})
REQUIRED_AUTHORIZATION_STRINGS = (
    "p008_record",
    "p005b_record",
    "matthew_out_of_band_record",
    "offline_bundle_review_record",
    "runtime_review_record",
)
REQUIRED_SERVER_FLAGS = (
    "--model",
    "--host",
    "--port",
    "--threads",
    "--threads-batch",
    "--batch-size",
    "--ubatch-size",
    "--n-gpu-layers",
    "--ctx-size",
    "--parallel",
    "--seed",
    "--device",
    "--list-devices",
)
WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}
WINDOWS_FORBIDDEN = frozenset('<>:"|?*')
HASH_CHUNK_SIZE = 1024 * 1024
NETWORK_TIMEOUT_SECONDS = 120
INSPECTION_TIMEOUT_SECONDS = 30
MAX_ZIP_MEMBER_BYTES = 8 * 1024 * 1024 * 1024
MAX_ZIP_GROUP_BYTES = 32 * 1024 * 1024 * 1024


# These are the publisher records captured from the GitHub release API and the
# official Qwen Hugging Face repository.  The authenticated downloads lock must
# match this exact allowlist; a lock cannot silently widen network authority.
OFFICIAL_ARTIFACTS: dict[tuple[str | None, str], dict[str, Any]] = {
    ("b11514", "llama-b11514-bin-win-cpu-x64.zip"): {
        "url": "https://github.com/ggml-org/llama.cpp/releases/download/b11514/llama-b11514-bin-win-cpu-x64.zip",
        "sha256": "5a1d6ba1b414ab0234b12e29d911b3b8fe63051b4455215e184cf74870eac596",
        "bytes": 19_484_487,
    },
    ("b11514", "llama-b11514-bin-win-vulkan-x64.zip"): {
        "url": "https://github.com/ggml-org/llama.cpp/releases/download/b11514/llama-b11514-bin-win-vulkan-x64.zip",
        "sha256": "e1eaddcde761b1f839b9c6d5924b97f2698fba22068ca3b63f129c3caf55b88f",
        "bytes": 33_446_009,
    },
    ("b11514", "llama-b11514-bin-win-cuda-12.4-x64.zip"): {
        "url": "https://github.com/ggml-org/llama.cpp/releases/download/b11514/llama-b11514-bin-win-cuda-12.4-x64.zip",
        "sha256": "2f71ffab0ee2f7493abe8d30b403fe2728d8a3c97bbb2baf85c7c222a94454fe",
        "bytes": 265_198_374,
    },
    ("b11514", "cudart-llama-bin-win-cuda-12.4-x64.zip"): {
        "url": "https://github.com/ggml-org/llama.cpp/releases/download/b11514/cudart-llama-bin-win-cuda-12.4-x64.zip",
        "sha256": "8c79a9b226de4b3cacfd1f83d24f962d0773be79f1e7b75c6af4ded7e32ae1d6",
        "bytes": 391_443_627,
    },
    ("b11513", "llama-b11513-bin-win-cpu-x64.zip"): {
        "url": "https://github.com/ggml-org/llama.cpp/releases/download/b11513/llama-b11513-bin-win-cpu-x64.zip",
        "sha256": "34166ebb2593b31b7f644a6e3fddaade42716fb4a12bb5bc3a6650ddc5ae1e39",
        "bytes": 19_485_365,
    },
    ("b11513", "llama-b11513-bin-win-vulkan-x64.zip"): {
        "url": "https://github.com/ggml-org/llama.cpp/releases/download/b11513/llama-b11513-bin-win-vulkan-x64.zip",
        "sha256": "7d9a635e3ef8d90a4b665ffb6f2449c783386829a35c8ac1372ae1f3537937ae",
        "bytes": 33_445_776,
    },
    ("b11513", "llama-b11513-bin-win-cuda-12.4-x64.zip"): {
        "url": "https://github.com/ggml-org/llama.cpp/releases/download/b11513/llama-b11513-bin-win-cuda-12.4-x64.zip",
        "sha256": "4f0f20744c59476333aad661aaca539d761299322889654193d609d98c67b407",
        "bytes": 265_198_141,
    },
    ("b11513", "cudart-llama-bin-win-cuda-12.4-x64.zip"): {
        "url": "https://github.com/ggml-org/llama.cpp/releases/download/b11513/cudart-llama-bin-win-cuda-12.4-x64.zip",
        "sha256": "8c79a9b226de4b3cacfd1f83d24f962d0773be79f1e7b75c6af4ded7e32ae1d6",
        "bytes": 391_443_627,
    },
    (None, MODEL_NAME): {
        "url": (
            "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/"
            "91cad51170dc346986eccefdc2dd33a9da36ead9/"
            "qwen2.5-1.5b-instruct-fp16.gguf"
        ),
        "sha256": "fc89e330deb3fd8fa560f1c0f35a1e2b8da96d59e13445559ed190307a6f5649",
        "bytes": 3_560_416_288,
    },
}


class ArtifactError(ValueError):
    """An artifact cannot be prepared under the authenticated plan."""


@dataclass(frozen=True)
class Artifact:
    name: str
    url: str
    sha256: str
    bytes: int
    version: str | None
    publisher: str

    @property
    def destination_group(self) -> str:
        return self.version or "model"

    def destination(self, root: Path) -> Path:
        return root / "downloads" / self.destination_group / self.name


@dataclass(frozen=True)
class ZipMember:
    archive_name: str
    relative: str
    is_directory: bool
    size: int


@dataclass
class ExtractionGroup:
    version: str
    backend: str
    release_artifact: Artifact
    sources: list[tuple[Artifact, list[ZipMember]]]

    def destination(self, root: Path) -> Path:
        return root / "downloads" / "extracted" / self.version / self.backend


def _json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ArtifactError(f"duplicate JSON key: {key!r}")
        value[key] = item
    return value


def _is_reparse(file_stat: os.stat_result) -> bool:
    marker = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(int(getattr(file_stat, "st_file_attributes", 0)) & marker)


def _reject_link(path: Path, file_stat: os.stat_result) -> None:
    if stat.S_ISLNK(file_stat.st_mode) or _is_reparse(file_stat):
        raise ArtifactError(f"symlink or reparse point is forbidden: {path}")


def _read_json(path: Path, *, label: str) -> Any:
    try:
        before = path.lstat()
        _reject_link(path, before)
        if not stat.S_ISREG(before.st_mode):
            raise ArtifactError(f"{label} must be a regular file")
        raw = path.read_bytes()
        after = path.lstat()
    except ArtifactError:
        raise
    except OSError as error:
        raise ArtifactError(f"cannot read {label}") from error
    _reject_link(path, after)
    signature_before = (
        before.st_dev, before.st_ino, before.st_size,
        getattr(before, "st_mtime_ns", None), before.st_mode,
    )
    signature_after = (
        after.st_dev, after.st_ino, after.st_size,
        getattr(after, "st_mtime_ns", None), after.st_mode,
    )
    if signature_before != signature_after:
        raise ArtifactError(f"{label} changed while it was read")
    try:
        return json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_json_object)
    except ArtifactError:
        raise
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ArtifactError(f"invalid {label}") from error


def _validate_component(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value or value in (".", ".."):
        raise ArtifactError(f"{label} must be a non-empty filename component")
    if ("/" in value or "\\" in value or "\x00" in value
            or value[-1] in (" ", ".") or len(value) > 240
            or any(ord(character) < 32 for character in value)
            or any(character in WINDOWS_FORBIDDEN for character in value)):
        raise ArtifactError(f"unsafe {label}: {value!r}")
    if value.split(".", 1)[0].upper() in WINDOWS_RESERVED:
        raise ArtifactError(f"Windows device name is forbidden in {label}: {value!r}")
    return value


def _authorization(root: Path) -> dict[str, Any]:
    document = _read_json(root / "state" / "authorization.json", label="authorization record")
    if not isinstance(document, dict):
        raise ArtifactError("authorization record must be a JSON object")
    for key in REQUIRED_AUTHORIZATION_STRINGS:
        value = document.get(key)
        if (not isinstance(value, str) or not value.strip()
                or "UNRESOLVED" in value.upper()):
            raise ArtifactError(f"missing recorded prerequisite: {key}")
    if document.get("desktop_specs_confirmed") is not True:
        raise ArtifactError("desktop specifications must be explicitly confirmed")
    return document


def _validate_url(url: str, *, initial: bool, resolve: bool) -> urllib.parse.SplitResult:
    if not isinstance(url, str):
        raise ArtifactError("artifact URL must be a string")
    try:
        parsed = urllib.parse.urlsplit(url)
        port = parsed.port
    except ValueError as error:
        raise ArtifactError("invalid artifact URL") from error
    host = (parsed.hostname or "").rstrip(".").lower()
    allowed = INITIAL_NETWORK_HOSTS if initial else ALLOWED_NETWORK_HOSTS
    if (parsed.scheme != "https" or host not in allowed or port not in (None, 443)
            or parsed.username is not None or parsed.password is not None
            or not parsed.path.startswith("/") or parsed.fragment):
        raise ArtifactError(f"URL is outside the HTTPS artifact allowlist: {url!r}")
    if initial and parsed.query:
        raise ArtifactError("pinned origin URLs must not contain a query")
    if resolve:
        _assert_public_host(host)
    return parsed


def _assert_public_host(host: str) -> None:
    try:
        addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError as error:
        raise ArtifactError(f"cannot resolve approved artifact host: {host}") from error
    if not addresses:
        raise ArtifactError(f"approved artifact host has no addresses: {host}")
    for address in addresses:
        raw = str(address[4][0]).split("%", 1)[0]
        try:
            parsed = ipaddress.ip_address(raw)
        except ValueError as error:
            raise ArtifactError(f"artifact host resolved to an invalid address: {host}") from error
        if not parsed.is_global:
            raise ArtifactError(f"artifact host resolved to a non-public address: {host}")


def _validate_origin(artifact: Artifact) -> None:
    parsed = _validate_url(artifact.url, initial=True, resolve=False)
    if urllib.parse.unquote(parsed.path) != parsed.path:
        raise ArtifactError("percent-encoded artifact paths are forbidden")
    if parsed.hostname.lower() == "github.com":
        expected_path = (
            f"/ggml-org/llama.cpp/releases/download/{artifact.version}/{artifact.name}"
        )
        if artifact.version is None or parsed.path != expected_path:
            raise ArtifactError(f"unexpected llama.cpp release URL for {artifact.name}")
    else:
        expected_prefix = (
            "/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/"
            "91cad51170dc346986eccefdc2dd33a9da36ead9/"
        )
        if artifact.version is not None or parsed.path != expected_prefix + artifact.name:
            raise ArtifactError(f"unexpected Qwen revision URL for {artifact.name}")


def _load_lock(root: Path) -> list[Artifact]:
    document = _read_json(root / "downloads.lock.json", label="downloads lock")
    if not isinstance(document, dict) or not isinstance(document.get("artifacts"), list):
        raise ArtifactError("downloads lock must contain an artifacts list")
    artifacts: list[Artifact] = []
    seen: set[tuple[str | None, str]] = set()
    destinations: set[str] = set()
    for index, record in enumerate(document["artifacts"]):
        if not isinstance(record, dict):
            raise ArtifactError(f"artifact {index} must be an object")
        required = {"name", "url", "sha256", "bytes", "publisher"}
        if set(record) not in (required, required | {"version"}):
            raise ArtifactError(
                f"artifact {index} must contain name, url, sha256, bytes, publisher, "
                "and optional version"
            )
        name = _validate_component(record["name"], label=f"artifact {index} name")
        version = record.get("version")
        if version is not None:
            version = _validate_component(version, label=f"artifact {index} version")
        sha256 = record["sha256"]
        size = record["bytes"]
        publisher = record["publisher"]
        if not isinstance(sha256, str) or not HASH_RE.fullmatch(sha256):
            raise ArtifactError(f"artifact {index} has an invalid SHA-256")
        if type(size) is not int or size <= 0:
            raise ArtifactError(f"artifact {index} has an invalid byte length")
        if not isinstance(publisher, str) or not publisher.strip():
            raise ArtifactError(f"artifact {index} has no publisher evidence")
        artifact = Artifact(
            name=name,
            url=record["url"],
            sha256=sha256.lower(),
            bytes=size,
            version=version,
            publisher=publisher.strip(),
        )
        key = (version, name)
        if key in seen:
            raise ArtifactError(f"duplicate artifact record: {version or 'model'}/{name}")
        seen.add(key)
        destination = f"{artifact.destination_group}/{name}".casefold()
        if destination in destinations:
            raise ArtifactError(f"case-colliding artifact destination: {destination}")
        destinations.add(destination)
        expected = OFFICIAL_ARTIFACTS.get(key)
        if expected is None:
            raise ArtifactError(f"artifact is outside the frozen allowlist: {key!r}")
        if any(getattr(artifact, field) != expected[field] for field in ("url", "sha256", "bytes")):
            raise ArtifactError(f"artifact metadata differs from the frozen publisher record: {name}")
        _validate_origin(artifact)
        artifacts.append(artifact)
    if seen != set(OFFICIAL_ARTIFACTS):
        missing = sorted(f"{version or 'model'}/{name}" for version, name in set(OFFICIAL_ARTIFACTS) - seen)
        extra = sorted(f"{version or 'model'}/{name}" for version, name in seen - set(OFFICIAL_ARTIFACTS))
        raise ArtifactError(f"downloads lock is not the complete frozen set; missing={missing}, extra={extra}")
    return sorted(artifacts, key=lambda item: (item.destination_group, item.name))


def _prepare(root: os.PathLike[str] | str, expected_manifest_sha256: str) -> tuple[Path, list[Artifact]]:
    root_path = Path(os.path.abspath(os.fspath(root)))
    verify_bundle.verify(
        root_path,
        root_path / "bundle-manifest.json",
        expected_manifest_sha256,
    )
    _authorization(root_path)
    return root_path, _load_lock(root_path)


def _file_signature(file_stat: os.stat_result) -> tuple[int, ...]:
    return (
        int(file_stat.st_mode), int(file_stat.st_size), int(file_stat.st_dev),
        int(file_stat.st_ino),
        int(getattr(file_stat, "st_mtime_ns", int(file_stat.st_mtime * 1_000_000_000))),
        int(getattr(file_stat, "st_file_attributes", 0)),
    )


def _hash_file(path: Path) -> tuple[str, int]:
    try:
        before = path.lstat()
    except OSError as error:
        raise ArtifactError(f"missing or unreadable artifact: {path}") from error
    _reject_link(path, before)
    if not stat.S_ISREG(before.st_mode):
        raise ArtifactError(f"artifact is not a regular file: {path}")
    digest = hashlib.sha256()
    size = 0
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as stream:
            for chunk in iter(lambda: stream.read(HASH_CHUNK_SIZE), b""):
                digest.update(chunk)
                size += len(chunk)
        after = path.lstat()
    except OSError as error:
        raise ArtifactError(f"cannot safely hash artifact: {path}") from error
    _reject_link(path, after)
    if _file_signature(before) != _file_signature(after) or size != after.st_size:
        raise ArtifactError(f"artifact changed while it was hashed: {path}")
    return digest.hexdigest(), size


def _assert_artifact(path: Path, artifact: Artifact) -> None:
    actual_hash, actual_size = _hash_file(path)
    if actual_size != artifact.bytes:
        raise ArtifactError(f"publisher byte length mismatch: {artifact.name}")
    if actual_hash != artifact.sha256:
        raise ArtifactError(f"publisher SHA-256 mismatch: {artifact.name}")


def _lstat_optional(path: Path) -> os.stat_result | None:
    try:
        return path.lstat()
    except FileNotFoundError:
        return None
    except OSError as error:
        raise ArtifactError(f"cannot inspect path: {path}") from error


def _check_directory_chain(root: Path, relative: tuple[str, ...], *, create: bool) -> Path:
    current = root
    root_stat = current.lstat()
    _reject_link(current, root_stat)
    if not stat.S_ISDIR(root_stat.st_mode):
        raise ArtifactError("bundle root is not a directory")
    for component in relative:
        _validate_component(component, label="directory component")
        current = current / component
        current_stat = _lstat_optional(current)
        if current_stat is None:
            if not create:
                return current
            try:
                current.mkdir()
                current_stat = current.lstat()
            except OSError as error:
                raise ArtifactError(f"cannot create artifact directory: {current}") from error
        _reject_link(current, current_stat)
        if not stat.S_ISDIR(current_stat.st_mode):
            raise ArtifactError(f"artifact path component is not a directory: {current}")
    return current


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if code not in (301, 302, 303, 307, 308) or req.get_method() != "GET":
            raise ArtifactError("artifact download used a forbidden redirect")
        _validate_url(newurl, initial=False, resolve=True)
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is None or redirected.get_method() != "GET":
            raise ArtifactError("artifact redirect did not preserve GET-only access")
        return redirected


def _network_opener() -> urllib.request.OpenerDirector:
    # An empty proxy mapping deliberately ignores proxy-related environment
    # variables and keeps the downloader free of proxy credentials.
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), _SafeRedirectHandler())


def _response_status(response: Any) -> int:
    status = getattr(response, "status", None)
    if status is None and hasattr(response, "getcode"):
        status = response.getcode()
    if type(status) is not int:
        raise ArtifactError("artifact response has no HTTP status")
    return status


def _download_one(artifact: Artifact, destination: Path, opener: Any) -> dict[str, Any]:
    _validate_url(artifact.url, initial=True, resolve=True)
    request = urllib.request.Request(
        artifact.url,
        headers={"User-Agent": "RedTeamHarness-P008/1", "Accept": "application/octet-stream"},
        method="GET",
    )
    created = False
    try:
        with opener.open(request, timeout=NETWORK_TIMEOUT_SECONDS) as response:
            if _response_status(response) != 200:
                raise ArtifactError(f"artifact server returned non-200 status for {artifact.name}")
            final_url = response.geturl()
            _validate_url(final_url, initial=(final_url == artifact.url), resolve=True)
            length = response.headers.get("Content-Length") if response.headers is not None else None
            if length is not None:
                if not str(length).isdigit() or int(length) != artifact.bytes:
                    raise ArtifactError(f"HTTP byte length differs from publisher record: {artifact.name}")
            _check_directory_chain(
                destination.parents[2],
                ("downloads", artifact.destination_group),
                create=True,
            )
            digest = hashlib.sha256()
            total = 0
            try:
                output = destination.open("xb")
                created = True
            except FileExistsError as error:
                raise ArtifactError(f"refusing to overwrite download: {destination}") from error
            with output:
                while True:
                    chunk = response.read(HASH_CHUNK_SIZE)
                    if not chunk:
                        break
                    if not isinstance(chunk, bytes):
                        raise ArtifactError("artifact response yielded non-byte content")
                    total += len(chunk)
                    if total > artifact.bytes:
                        raise ArtifactError(f"artifact exceeded publisher byte length: {artifact.name}")
                    digest.update(chunk)
                    output.write(chunk)
            if total != artifact.bytes or digest.hexdigest() != artifact.sha256:
                raise ArtifactError(f"download failed publisher integrity check: {artifact.name}")
        _assert_artifact(destination, artifact)
    except Exception:
        if created:
            try:
                destination.unlink()
            except OSError:
                pass
        raise
    return {
        "name": artifact.name,
        "path": destination.relative_to(destination.parents[2]).as_posix(),
        "sha256": artifact.sha256,
        "bytes": artifact.bytes,
        "status": "downloaded",
    }


def fetch(root: os.PathLike[str] | str, expected_manifest_sha256: str) -> dict[str, Any]:
    root_path, artifacts = _prepare(root, expected_manifest_sha256)
    missing: list[Artifact] = []
    results: list[dict[str, Any]] = []
    for artifact in artifacts:
        _check_directory_chain(root_path, ("downloads", artifact.destination_group), create=False)
        destination = artifact.destination(root_path)
        target_stat = _lstat_optional(destination)
        if target_stat is None:
            missing.append(artifact)
            continue
        _reject_link(destination, target_stat)
        _assert_artifact(destination, artifact)
        results.append({
            "name": artifact.name,
            "path": destination.relative_to(root_path).as_posix(),
            "sha256": artifact.sha256,
            "bytes": artifact.bytes,
            "status": "already_verified",
        })
    opener = _network_opener() if missing else None
    for artifact in missing:
        assert opener is not None
        result = _download_one(artifact, artifact.destination(root_path), opener)
        # _download_one uses the bundle root as destination.parents[2].  Replace
        # that defensive local calculation with the canonical relative path.
        result["path"] = artifact.destination(root_path).relative_to(root_path).as_posix()
        results.append(result)
    results.sort(key=lambda item: item["path"])
    return {"status": "artifacts verified", "artifacts": results}


def _zip_member(info: zipfile.ZipInfo) -> ZipMember:
    name = info.filename
    if not isinstance(name, str) or not name or "\\" in name or "\x00" in name:
        raise ArtifactError(f"unsafe ZIP member name: {name!r}")
    directory = info.is_dir()
    raw = name[:-1] if directory and name.endswith("/") else name
    if not raw or raw.startswith("/"):
        raise ArtifactError(f"unsafe ZIP member path: {name!r}")
    components = raw.split("/")
    if any(component in ("", ".", "..") for component in components):
        raise ArtifactError(f"ZIP traversal or ambiguous path: {name!r}")
    for component in components:
        _validate_component(component, label="ZIP member component")
    relative = PurePosixPath(*components).as_posix()
    unix_mode = (info.external_attr >> 16) & 0xFFFF
    unix_type = stat.S_IFMT(unix_mode)
    if unix_type == stat.S_IFLNK:
        raise ArtifactError(f"ZIP symlink is forbidden: {name!r}")
    if unix_type not in (0, stat.S_IFREG, stat.S_IFDIR):
        raise ArtifactError(f"ZIP special file is forbidden: {name!r}")
    if directory and unix_type == stat.S_IFREG:
        raise ArtifactError(f"ZIP member type disagrees with its path: {name!r}")
    if not directory and unix_type == stat.S_IFDIR:
        raise ArtifactError(f"ZIP member type disagrees with its path: {name!r}")
    if info.flag_bits & 0x1:
        raise ArtifactError(f"encrypted ZIP member is forbidden: {name!r}")
    if info.file_size < 0 or info.file_size > MAX_ZIP_MEMBER_BYTES:
        raise ArtifactError(f"ZIP member has an unsafe expanded size: {name!r}")
    return ZipMember(name, relative, directory, info.file_size)


def _read_zip_members(path: Path) -> list[ZipMember]:
    try:
        with zipfile.ZipFile(path, "r") as archive:
            members: list[ZipMember] = []
            seen: dict[str, str] = {}
            total = 0
            for info in archive.infolist():
                member = _zip_member(info)
                folded = member.relative.casefold()
                previous = seen.get(folded)
                if previous is not None:
                    kind = "duplicate" if previous == member.relative else "case-colliding"
                    raise ArtifactError(
                        f"{kind} ZIP members: {previous!r} and {member.relative!r}"
                    )
                seen[folded] = member.relative
                if not member.is_directory:
                    total += member.size
                    if total > MAX_ZIP_GROUP_BYTES:
                        raise ArtifactError("ZIP archive expands beyond the safety limit")
                members.append(member)
            return members
    except ArtifactError:
        raise
    except (OSError, zipfile.BadZipFile, RuntimeError) as error:
        raise ArtifactError(f"invalid ZIP archive: {path.name}") from error


def _classify_release(artifact: Artifact) -> tuple[str, str] | tuple[str, "cudart"] | None:
    build_match = BUILD_RE.fullmatch(artifact.name)
    if build_match:
        version, variant = build_match.groups()
        backend = "cuda" if variant == "cuda-12.4" else variant
        if artifact.version != version:
            raise ArtifactError(f"release tag differs from archive name: {artifact.name}")
        return version, backend
    if CUDART_RE.fullmatch(artifact.name):
        if artifact.version not in ("b11513", "b11514"):
            raise ArtifactError(f"CUDA runtime archive has an invalid release tag: {artifact.name}")
        return artifact.version, "cudart"
    return None


def _combine_members(group: ExtractionGroup) -> None:
    files: dict[str, str] = {}
    directories: dict[str, str] = {}
    for _, members in group.sources:
        for member in members:
            parts = PurePosixPath(member.relative).parts
            for count in range(1, len(parts)):
                ancestor = PurePosixPath(*parts[:count]).as_posix()
                folded_ancestor = ancestor.casefold()
                if folded_ancestor in files:
                    raise ArtifactError(f"ZIP file is used as a directory: {ancestor!r}")
                previous_directory = directories.get(folded_ancestor)
                if previous_directory is not None and previous_directory != ancestor:
                    raise ArtifactError(
                        f"case-colliding ZIP directories: {previous_directory!r} and {ancestor!r}"
                    )
                directories[folded_ancestor] = ancestor
            folded = member.relative.casefold()
            if member.is_directory:
                if folded in files:
                    raise ArtifactError(f"ZIP path is both a file and directory: {member.relative!r}")
                previous = directories.get(folded)
                if previous is not None and previous != member.relative:
                    raise ArtifactError(
                        f"case-colliding ZIP directories: {previous!r} and {member.relative!r}"
                    )
                directories[folded] = member.relative
            else:
                if folded in directories:
                    raise ArtifactError(f"ZIP path is both a file and directory: {member.relative!r}")
                previous = files.get(folded)
                if previous is not None:
                    raise ArtifactError(
                        f"conflicting files while merging runtime archives: {previous!r} and {member.relative!r}"
                    )
                files[folded] = member.relative
    if "llama-server.exe" not in files or files["llama-server.exe"] != "llama-server.exe":
        raise ArtifactError(
            f"{group.version}/{group.backend} does not contain root-level llama-server.exe"
        )


def _archive_groups(root: Path, artifacts: list[Artifact]) -> list[ExtractionGroup]:
    archives = [artifact for artifact in artifacts if artifact.name.lower().endswith(".zip")]
    # The complete archive set is authenticated before even central directories
    # are parsed, so extraction cannot begin from a partially verified set.
    for artifact in archives:
        _assert_artifact(artifact.destination(root), artifact)
    builds: dict[tuple[str, str], tuple[Artifact, list[ZipMember]]] = {}
    runtimes: dict[str, tuple[Artifact, list[ZipMember]]] = {}
    for artifact in archives:
        classification = _classify_release(artifact)
        if classification is None:
            continue
        members = _read_zip_members(artifact.destination(root))
        version, backend = classification
        if backend == "cudart":
            if version in runtimes:
                raise ArtifactError(f"duplicate CUDA runtime archive for {version}")
            runtimes[version] = (artifact, members)
        else:
            key = (version, backend)
            if key in builds:
                raise ArtifactError(f"duplicate build archive for {version}/{backend}")
            builds[key] = (artifact, members)
    if set(builds) != EXPECTED_BUILDS or set(runtimes) != {"b11513", "b11514"}:
        raise ArtifactError("release archive set is incomplete")
    groups: list[ExtractionGroup] = []
    for key in sorted(builds):
        artifact, members = builds[key]
        sources = [(artifact, members)]
        if key[1] == "cuda":
            sources.append(runtimes[key[0]])
        group = ExtractionGroup(key[0], key[1], artifact, sources)
        _combine_members(group)
        groups.append(group)
    return groups


def _create_directory(path: Path, created_directories: list[Path]) -> None:
    existing = _lstat_optional(path)
    if existing is not None:
        _reject_link(path, existing)
        if not stat.S_ISDIR(existing.st_mode):
            raise ArtifactError(f"extraction path is not a directory: {path}")
        return
    path.mkdir()
    created_directories.append(path)


def _extract_group(root: Path, group: ExtractionGroup) -> None:
    destination = group.destination(root)
    created_files: list[Path] = []
    created_directories: list[Path] = []
    try:
        parent = destination.parent
        _create_directory(root / "downloads", created_directories)
        _create_directory(root / "downloads" / "extracted", created_directories)
        _create_directory(parent, created_directories)
        _create_directory(destination, created_directories)
        for artifact, members in group.sources:
            _assert_artifact(artifact.destination(root), artifact)
            member_by_name = {member.archive_name: member for member in members}
            with zipfile.ZipFile(artifact.destination(root), "r") as archive:
                for info in archive.infolist():
                    member = member_by_name[info.filename]
                    target = destination.joinpath(*PurePosixPath(member.relative).parts)
                    if member.is_directory:
                        _create_directory(target, created_directories)
                        continue
                    current = destination
                    for component in PurePosixPath(member.relative).parts[:-1]:
                        current = current / component
                        _create_directory(current, created_directories)
                    try:
                        output = target.open("xb")
                        created_files.append(target)
                    except FileExistsError as error:
                        raise ArtifactError(f"refusing to overwrite extracted file: {target}") from error
                    written = 0
                    with archive.open(info, "r") as source, output:
                        while True:
                            chunk = source.read(HASH_CHUNK_SIZE)
                            if not chunk:
                                break
                            written += len(chunk)
                            if written > member.size:
                                raise ArtifactError(f"ZIP member exceeded declared size: {member.relative}")
                            output.write(chunk)
                    if written != member.size:
                        raise ArtifactError(f"ZIP member size mismatch: {member.relative}")
            _assert_artifact(artifact.destination(root), artifact)
    except Exception:
        for file_path in reversed(created_files):
            try:
                file_path.unlink()
            except OSError:
                pass
        for directory in sorted(created_directories, key=lambda item: len(item.parts), reverse=True):
            try:
                directory.rmdir()
            except OSError:
                pass
        raise


def extract(root: os.PathLike[str] | str, expected_manifest_sha256: str) -> dict[str, Any]:
    root_path, artifacts = _prepare(root, expected_manifest_sha256)
    groups = _archive_groups(root_path, artifacts)
    # Fail the whole command before mutation if any destination already exists.
    for group in groups:
        _check_directory_chain(root_path, ("downloads", "extracted", group.version), create=False)
        if _lstat_optional(group.destination(root_path)) is not None:
            raise ArtifactError(f"refusing to overwrite extracted build: {group.version}/{group.backend}")
    extracted: list[dict[str, Any]] = []
    for group in groups:
        _extract_group(root_path, group)
        extracted.append({
            "version": group.version,
            "backend": group.backend,
            "path": group.destination(root_path).relative_to(root_path).as_posix(),
            "release_asset_sha256": group.release_artifact.sha256,
            "merged_cuda_runtime": group.backend == "cuda",
        })
    return {"status": "archives safely extracted", "builds": extracted}


def _hash_zip_file(archive: zipfile.ZipFile, member: ZipMember) -> str:
    digest = hashlib.sha256()
    total = 0
    try:
        with archive.open(member.archive_name, "r") as stream:
            while True:
                chunk = stream.read(HASH_CHUNK_SIZE)
                if not chunk:
                    break
                total += len(chunk)
                if total > member.size:
                    raise ArtifactError(f"ZIP member exceeded declared size: {member.relative}")
                digest.update(chunk)
    except (OSError, RuntimeError, zipfile.BadZipFile) as error:
        raise ArtifactError(f"cannot hash ZIP member: {member.relative}") from error
    if total != member.size:
        raise ArtifactError(f"ZIP member size mismatch: {member.relative}")
    return digest.hexdigest()


def _expected_group_files(root: Path, group: ExtractionGroup) -> dict[str, str]:
    expected: dict[str, str] = {}
    for artifact, members in group.sources:
        _assert_artifact(artifact.destination(root), artifact)
        with zipfile.ZipFile(artifact.destination(root), "r") as archive:
            for member in members:
                if member.is_directory:
                    continue
                if member.relative.casefold() in {name.casefold() for name in expected}:
                    raise ArtifactError(f"duplicate merged runtime member: {member.relative}")
                expected[member.relative] = _hash_zip_file(archive, member)
        _assert_artifact(artifact.destination(root), artifact)
    return expected


def _scan_extracted(destination: Path) -> dict[str, Path]:
    destination_stat = _lstat_optional(destination)
    if destination_stat is None:
        raise ArtifactError(f"extracted build is missing: {destination}")
    _reject_link(destination, destination_stat)
    if not stat.S_ISDIR(destination_stat.st_mode):
        raise ArtifactError(f"extracted build path is not a directory: {destination}")
    files: dict[str, Path] = {}
    folded: dict[str, str] = {}
    pending: list[tuple[Path, PurePosixPath | None]] = [(destination, None)]
    while pending:
        directory, prefix = pending.pop()
        try:
            entries = sorted(os.scandir(directory), key=lambda entry: entry.name)
        except OSError as error:
            raise ArtifactError(f"cannot scan extracted build: {destination}") from error
        for entry in entries:
            relative_path = PurePosixPath(entry.name) if prefix is None else prefix / entry.name
            relative = relative_path.as_posix()
            for component in relative_path.parts:
                _validate_component(component, label="extracted path component")
            try:
                entry_stat = entry.stat(follow_symlinks=False)
            except OSError as error:
                raise ArtifactError(f"cannot inspect extracted entry: {relative}") from error
            path = Path(entry.path)
            _reject_link(path, entry_stat)
            previous = folded.get(relative.casefold())
            if previous is not None and previous != relative:
                raise ArtifactError(f"case-colliding extracted paths: {previous!r} and {relative!r}")
            folded[relative.casefold()] = relative
            if stat.S_ISDIR(entry_stat.st_mode):
                pending.append((path, relative_path))
            elif stat.S_ISREG(entry_stat.st_mode):
                files[relative] = path
            else:
                raise ArtifactError(f"non-regular extracted entry: {relative}")
    return files


def _verify_extracted(destination: Path, expected: dict[str, str]) -> dict[str, str]:
    actual_paths = _scan_extracted(destination)
    actual_folded = {name.casefold(): name for name in actual_paths}
    expected_folded = {name.casefold(): name for name in expected}
    if actual_folded != expected_folded:
        missing = sorted(set(expected_folded) - set(actual_folded))
        extra = sorted(set(actual_folded) - set(expected_folded))
        raise ArtifactError(f"extracted tree differs from archives; missing={missing}, extra={extra}")
    actual_hashes: dict[str, str] = {}
    for folded, expected_name in sorted(expected_folded.items()):
        actual_name = actual_folded[folded]
        if actual_name != expected_name:
            raise ArtifactError(f"extracted filename case differs from archive: {actual_name!r}")
        digest, _ = _hash_file(actual_paths[actual_name])
        if digest != expected[expected_name]:
            raise ArtifactError(f"extracted file differs from verified archive: {expected_name}")
        actual_hashes[actual_name] = digest
    return actual_hashes


def _process_options() -> dict[str, Any]:
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


def _invoke_inspection(binary: Path, argument: str) -> str:
    if argument not in ("--version", "--help", "--list-devices"):
        raise ArtifactError("inspection attempted an unapproved binary argument")
    try:
        result = subprocess.run(
            [os.fspath(binary), argument],
            cwd=binary.parent,
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=INSPECTION_TIMEOUT_SECONDS,
            shell=False,
            **_process_options(),
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise ArtifactError(f"llama-server inspection failed for {argument}") from error
    if result.returncode != 0:
        raise ArtifactError(f"llama-server {argument} exited with {result.returncode}")
    output = result.stdout.strip()
    if not output:
        raise ArtifactError(f"llama-server {argument} produced no output")
    return output


def _has_help_flag(help_output: str, flag: str) -> bool:
    return re.search(rf"(?<![A-Za-z0-9_-]){re.escape(flag)}(?![A-Za-z0-9_-])", help_output) is not None


def _parse_devices(output: str) -> list[dict[str, str]]:
    devices: list[dict[str, str]] = []
    seen: set[str] = set()
    for line in output.splitlines():
        match = re.fullmatch(r"\s*((?:CUDA|Vulkan)\d+):\s*(\S(?:.*\S)?)\s*", line, re.IGNORECASE)
        if not match:
            continue
        raw_id, description = match.groups()
        prefix_match = re.fullmatch(r"(CUDA|Vulkan)(\d+)", raw_id, re.IGNORECASE)
        assert prefix_match is not None
        identifier = prefix_match.group(1).capitalize() + prefix_match.group(2)
        if identifier.startswith("Cuda"):
            identifier = "CUDA" + prefix_match.group(2)
        if identifier.casefold() in seen:
            raise ArtifactError(f"duplicate device identifier in --list-devices: {identifier}")
        if len(description) > 300 or any(ord(character) < 32 for character in description):
            raise ArtifactError("unsafe device description")
        seen.add(identifier.casefold())
        devices.append({"id": identifier, "description": description})
    return devices


def _select_gpu_device(backend: str, devices: list[dict[str, str]]) -> str:
    prefix = "CUDA" if backend == "cuda" else "Vulkan"
    name_pattern = re.compile(
        rf"{re.escape(EXPECTED_GPU_NAME)}(?:\s+\([^\r\n]*\))?\Z",
        re.IGNORECASE,
    )
    matches = [
        item for item in devices
        if item["id"].startswith(prefix) and name_pattern.fullmatch(item["description"])
    ]
    if len(matches) != 1:
        raise ArtifactError(
            f"{backend} must expose exactly one {EXPECTED_GPU_NAME}; found {len(matches)}"
        )
    return matches[0]["id"]


def inspect(root: os.PathLike[str] | str, expected_manifest_sha256: str) -> dict[str, Any]:
    root_path, artifacts = _prepare(root, expected_manifest_sha256)
    builds_path = root_path / "state" / "builds.json"
    if _lstat_optional(builds_path) is not None:
        raise ArtifactError("refusing to overwrite state/builds.json")
    groups = _archive_groups(root_path, artifacts)

    # Authenticate every extracted byte for every build before invoking even
    # one executable.  This keeps a late corrupt build from producing partial
    # inspection state for earlier builds.
    prepared: list[tuple[ExtractionGroup, dict[str, str], dict[str, str]]] = []
    for group in groups:
        expected = _expected_group_files(root_path, group)
        actual = _verify_extracted(group.destination(root_path), expected)
        runtime = {
            name: digest for name, digest in sorted(actual.items())
            if Path(name).suffix.lower() in (".exe", ".dll")
        }
        if "llama-server.exe" not in runtime:
            raise ArtifactError(f"verified build lacks llama-server.exe: {group.version}/{group.backend}")
        prepared.append((group, expected, runtime))

    records: list[dict[str, Any]] = []
    for group, expected, runtime in prepared:
        destination = group.destination(root_path)
        # Close the time window between the all-build assertion and execution.
        _verify_extracted(destination, expected)
        binary = destination / "llama-server.exe"
        version_output = _invoke_inspection(binary, "--version")
        help_output = _invoke_inspection(binary, "--help")
        missing_flags = [flag for flag in REQUIRED_SERVER_FLAGS if not _has_help_flag(help_output, flag)]
        if missing_flags:
            raise ArtifactError(
                f"{group.version}/{group.backend} lacks required CLI flags: {missing_flags}"
            )
        listing_output = _invoke_inspection(binary, "--list-devices")
        devices = _parse_devices(listing_output)
        record: dict[str, Any] = {
            "version": group.version,
            "backend": group.backend,
            "binary": binary.relative_to(root_path).as_posix(),
            "binary_sha256": runtime["llama-server.exe"],
            "runtime_files_sha256": runtime,
            "release_asset_sha256": group.release_artifact.sha256,
            "version_output": version_output,
            "version_output_sha256": hashlib.sha256(version_output.encode("utf-8")).hexdigest(),
            "help_output_sha256": hashlib.sha256(help_output.encode("utf-8")).hexdigest(),
            "device_listing": {
                "output_sha256": hashlib.sha256(listing_output.encode("utf-8")).hexdigest(),
                "devices": devices,
            },
        }
        if group.backend != "cpu":
            record["device"] = _select_gpu_device(group.backend, devices)
        # Detect mutation by the inspected process before accepting its record.
        after = _verify_extracted(destination, expected)
        after_runtime = {
            name: digest for name, digest in sorted(after.items())
            if Path(name).suffix.lower() in (".exe", ".dll")
        }
        if after_runtime != runtime:
            raise ArtifactError(f"runtime changed during inspection: {group.version}/{group.backend}")
        records.append(record)

    _check_directory_chain(root_path, ("state",), create=True)
    document = {"schema_version": 1, "status": "verified", "builds": records}
    try:
        with builds_path.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(document, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
    except FileExistsError as error:
        raise ArtifactError("refusing to overwrite state/builds.json") from error
    return document


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("fetch", "extract", "inspect"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("--root", type=Path, required=True)
        subparser.add_argument("--expected-manifest-sha256", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    operation = {"fetch": fetch, "extract": extract, "inspect": inspect}[arguments.command]
    try:
        result = operation(arguments.root, arguments.expected_manifest_sha256)
    except (ArtifactError, verify_bundle.VerificationError, urllib.error.URLError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Verify an offline desktop bundle against an externally authenticated manifest.

The manifest is data, not a trust anchor.  Callers must supply its SHA-256 from
an independent channel with ``--expected-manifest-sha256``.  Run the bundled
copy with ``python -B`` so Python does not create an unexpected ``__pycache__``
before verification.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
from typing import Any


SCHEMA_VERSION = 1
MANIFEST_NAME = "bundle-manifest.json"
ALLOWED_MUTABLE_ROOTS = ("runtime", "downloads", "state", "results", "return")
HASH_RE = re.compile(r"[0-9a-fA-F]{64}\Z")
WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}
WINDOWS_FORBIDDEN_CHARS = frozenset('<>:"|?*')
INVENTORY_TIMEOUT_SECONDS = 15
HASH_CHUNK_SIZE = 1024 * 1024


class VerificationError(ValueError):
    """The bundle cannot be authenticated under the supplied manifest hash."""


def _file_attributes(file_stat: os.stat_result) -> int:
    return int(getattr(file_stat, "st_file_attributes", 0))


def _is_reparse_point(file_stat: os.stat_result) -> bool:
    marker = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(_file_attributes(file_stat) & marker)


def _entry_signature(file_stat: os.stat_result) -> tuple[int, ...]:
    return (
        int(file_stat.st_mode),
        int(file_stat.st_size),
        int(getattr(file_stat, "st_mtime_ns", int(file_stat.st_mtime * 1_000_000_000))),
        int(file_stat.st_dev),
        int(file_stat.st_ino),
        _file_attributes(file_stat),
    )


def _reject_link_or_reparse(path_label: str, file_stat: os.stat_result) -> None:
    if stat.S_ISLNK(file_stat.st_mode) or _is_reparse_point(file_stat):
        raise VerificationError(f"symlink or reparse point is forbidden: {path_label}")


def _reject_hard_link(path_label: str, file_stat: os.stat_result) -> None:
    if stat.S_ISREG(file_stat.st_mode) and int(getattr(file_stat, "st_nlink", 1)) > 1:
        raise VerificationError(f"hard-linked file is forbidden: {path_label}")


def _is_secret_component(component: str) -> bool:
    folded = component.casefold()
    return folded == ".env" or folded.startswith(".env.")


def _validate_relative_posix_path(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise VerificationError(f"{label} must be a non-empty relative POSIX path")
    if "\\" in value or "\x00" in value:
        raise VerificationError(f"unsafe path in {label}: {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or value != path.as_posix() or not path.parts:
        raise VerificationError(f"unsafe or non-canonical path in {label}: {value!r}")
    for component in path.parts:
        if component in ("", ".", ".."):
            raise VerificationError(f"path traversal in {label}: {value!r}")
        if (component[-1:] in (" ", ".")
                or any(character in WINDOWS_FORBIDDEN_CHARS or ord(character) < 32
                       for character in component)):
            raise VerificationError(f"Windows-unsafe path in {label}: {value!r}")
        if component.split(".", 1)[0].upper() in WINDOWS_RESERVED:
            raise VerificationError(f"Windows-reserved path in {label}: {value!r}")
        if _is_secret_component(component):
            raise VerificationError(f"secret .env path is forbidden: {value!r}")
    return value


def _under_mutable_root(relative_path: str, mutable_roots: tuple[str, ...]) -> bool:
    return PurePosixPath(relative_path).parts[0] in mutable_roots


def _absolute(path: Path) -> Path:
    """Return an absolute path without resolving links or reparse points."""
    return Path(os.path.abspath(os.fspath(path)))


def _prepare_root(root: os.PathLike[str] | str) -> Path:
    root_path = _absolute(Path(root))
    try:
        root_stat = root_path.lstat()
    except OSError as error:
        raise VerificationError("bundle root does not exist or is unreadable") from error
    _reject_link_or_reparse("bundle root", root_stat)
    if not stat.S_ISDIR(root_stat.st_mode):
        raise VerificationError("bundle root is not a directory")
    return root_path


def _prepare_manifest_path(root: Path, manifest_path: os.PathLike[str] | str) -> tuple[Path, str]:
    candidate = Path(manifest_path)
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = _absolute(candidate)
    try:
        common = Path(os.path.commonpath((os.fspath(root), os.fspath(candidate))))
    except ValueError as error:
        raise VerificationError("manifest must be inside the bundle root") from error
    if os.path.normcase(os.fspath(common)) != os.path.normcase(os.fspath(root)):
        raise VerificationError("manifest must be inside the bundle root")
    relative_native = os.path.relpath(candidate, root)
    if relative_native == os.curdir:
        raise VerificationError("manifest path names the bundle root")
    relative = Path(relative_native).as_posix()
    _validate_relative_posix_path(relative, label="manifest path")
    if _under_mutable_root(relative, ALLOWED_MUTABLE_ROOTS):
        raise VerificationError("manifest cannot be stored under a mutable root")

    current = root
    for component in PurePosixPath(relative).parts:
        current = current / component
        try:
            current_stat = current.lstat()
        except OSError as error:
            raise VerificationError("manifest is missing or unreadable") from error
        _reject_link_or_reparse(relative, current_stat)
    if not stat.S_ISREG(current_stat.st_mode):
        raise VerificationError("manifest is not a regular file")
    return candidate, relative


def _open_readonly_no_follow(path: Path) -> int:
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        return os.open(path, flags)
    except OSError as error:
        raise VerificationError(f"cannot safely read {path.name!r}") from error


def _digest_file(path: Path, *, capture: bool = False) -> tuple[str, int, bytes | None]:
    try:
        before = path.lstat()
    except OSError as error:
        raise VerificationError(f"missing or unreadable file: {path.name!r}") from error
    _reject_link_or_reparse(path.name, before)
    if not stat.S_ISREG(before.st_mode):
        raise VerificationError(f"expected a regular file: {path.name!r}")
    _reject_hard_link(path.name, before)

    digest = hashlib.sha256()
    size = 0
    captured = bytearray() if capture else None
    descriptor = _open_readonly_no_follow(path)
    try:
        opened = os.fstat(descriptor)
        _reject_link_or_reparse(path.name, opened)
        _reject_hard_link(path.name, opened)
        if not stat.S_ISREG(opened.st_mode) or _entry_signature(opened) != _entry_signature(before):
            raise VerificationError(f"file changed while it was opened: {path.name!r}")
        with os.fdopen(descriptor, "rb", closefd=True) as stream:
            descriptor = -1
            while True:
                chunk = stream.read(HASH_CHUNK_SIZE)
                if not chunk:
                    break
                digest.update(chunk)
                size += len(chunk)
                if captured is not None:
                    captured.extend(chunk)
    finally:
        if descriptor >= 0:
            os.close(descriptor)

    try:
        after = path.lstat()
    except OSError as error:
        raise VerificationError(f"file disappeared during verification: {path.name!r}") from error
    _reject_link_or_reparse(path.name, after)
    if _entry_signature(after) != _entry_signature(before) or size != before.st_size:
        raise VerificationError(f"file changed during verification: {path.name!r}")
    return digest.hexdigest(), size, bytes(captured) if captured is not None else None


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise VerificationError(f"duplicate JSON key in manifest: {key!r}")
        result[key] = value
    return result


def _load_manifest(
    manifest_bytes: bytes,
    manifest_relative: str,
) -> tuple[dict[str, dict[str, Any]], tuple[str, ...]]:
    try:
        text = manifest_bytes.decode("utf-8")
    except UnicodeDecodeError as error:
        raise VerificationError("manifest is not valid UTF-8") from error
    try:
        document = json.loads(text, object_pairs_hook=_no_duplicate_keys)
    except json.JSONDecodeError as error:
        raise VerificationError(f"manifest is not valid JSON: {error.msg}") from error
    if not isinstance(document, dict):
        raise VerificationError("manifest root must be an object")
    required_keys = {"schema_version", "files", "allowed_mutable_roots"}
    if set(document) != required_keys:
        raise VerificationError("manifest must contain exactly schema_version, files, and allowed_mutable_roots")
    if type(document["schema_version"]) is not int or document["schema_version"] != SCHEMA_VERSION:
        raise VerificationError(f"unsupported manifest schema_version; expected {SCHEMA_VERSION}")

    mutable = document["allowed_mutable_roots"]
    if (not isinstance(mutable, list)
            or any(not isinstance(item, str) for item in mutable)
            or len(mutable) != len(set(mutable))
            or not set(mutable).issubset(ALLOWED_MUTABLE_ROOTS)):
        raise VerificationError(
            "allowed_mutable_roots must be a duplicate-free subset of: "
            + ", ".join(ALLOWED_MUTABLE_ROOTS)
        )
    mutable_roots = tuple(mutable)

    files = document["files"]
    if not isinstance(files, dict):
        raise VerificationError("manifest files must be an object")
    validated: dict[str, dict[str, Any]] = {}
    case_paths: dict[str, str] = {}
    for relative, record in files.items():
        relative = _validate_relative_posix_path(relative, label="manifest files key")
        folded = relative.casefold()
        previous = case_paths.get(folded)
        if previous is not None and previous != relative:
            raise VerificationError(f"case-colliding manifest paths: {previous!r} and {relative!r}")
        case_paths[folded] = relative
        if folded == manifest_relative.casefold():
            raise VerificationError("the bundle manifest must not list or authenticate itself")
        if not isinstance(record, dict) or set(record) != {"sha256", "size"}:
            raise VerificationError(f"file record must contain exactly sha256 and size: {relative!r}")
        sha256 = record["sha256"]
        size = record["size"]
        if not isinstance(sha256, str) or not HASH_RE.fullmatch(sha256):
            raise VerificationError(f"invalid SHA-256 for {relative!r}")
        if type(size) is not int or size < 0:
            raise VerificationError(f"invalid byte size for {relative!r}")
        validated[relative] = {"sha256": sha256.lower(), "size": size}

    if "verify_bundle.py" not in validated:
        raise VerificationError("manifest must pin verify_bundle.py")
    return validated, mutable_roots


def _scan_tree(
    root: Path,
    mutable_roots: tuple[str, ...],
) -> dict[str, tuple[Path, str, tuple[int, ...]]]:
    """Return every descendant without following links or reparse points."""
    scanned: dict[str, tuple[Path, str, tuple[int, ...]]] = {}
    folded_paths: dict[str, str] = {}
    pending: list[tuple[Path, PurePosixPath | None]] = [(root, None)]
    while pending:
        directory, prefix = pending.pop()
        try:
            with os.scandir(directory) as iterator:
                entries = sorted(iterator, key=lambda item: item.name)
        except OSError as error:
            raise VerificationError("bundle tree is unreadable") from error
        for entry in entries:
            relative_path = PurePosixPath(entry.name) if prefix is None else prefix / entry.name
            relative = relative_path.as_posix()
            _validate_relative_posix_path(relative, label="bundle entry")
            try:
                entry_stat = entry.stat(follow_symlinks=False)
            except OSError as error:
                raise VerificationError(f"cannot inspect bundle entry: {relative!r}") from error
            _reject_link_or_reparse(relative, entry_stat)
            folded = relative.casefold()
            previous = folded_paths.get(folded)
            if previous is not None and previous != relative:
                raise VerificationError(f"case-colliding bundle paths: {previous!r} and {relative!r}")
            folded_paths[folded] = relative

            if stat.S_ISDIR(entry_stat.st_mode):
                kind = "directory"
                pending.append((Path(entry.path), relative_path))
            elif stat.S_ISREG(entry_stat.st_mode):
                kind = "file"
                _reject_hard_link(relative, entry_stat)
                if len(relative_path.parts) == 1 and relative in mutable_roots:
                    raise VerificationError(f"mutable root must be a directory: {relative!r}")
            else:
                raise VerificationError(f"special filesystem entry is forbidden: {relative!r}")
            scanned[relative] = (Path(entry.path), kind, _entry_signature(entry_stat))
    return scanned


def _validate_tree_shape(
    scanned: dict[str, tuple[Path, str, tuple[int, ...]]],
    declared: dict[str, dict[str, Any]],
    manifest_relative: str,
    mutable_roots: tuple[str, ...],
) -> None:
    actual_case = {relative.casefold(): relative for relative in scanned}
    for relative in declared:
        actual = actual_case.get(relative.casefold())
        if actual is None:
            raise VerificationError(f"missing declared file: {relative!r}")
        if actual != relative:
            raise VerificationError(f"path case mismatch: manifest {relative!r}, bundle {actual!r}")
        if scanned[relative][1] != "file":
            raise VerificationError(f"declared path is not a regular file: {relative!r}")

    for relative, (_, kind, _) in scanned.items():
        if kind != "file" or relative == manifest_relative or relative in declared:
            continue
        if _under_mutable_root(relative, mutable_roots):
            continue
        raise VerificationError(f"unexpected file outside mutable roots: {relative!r}")


def verify(
    root: os.PathLike[str] | str,
    manifest_path: os.PathLike[str] | str,
    expected_manifest_sha256: str,
) -> dict[str, Any]:
    """Authenticate *manifest_path* externally, then verify the closed bundle.

    Every listed file is authenticated, including listed files below a mutable
    root.  Only unlisted descendants of the manifest's declared mutable roots
    are outside this verification claim and need separate checks later.
    """
    if not isinstance(expected_manifest_sha256, str):
        raise VerificationError("expected manifest SHA-256 is required")
    expected = expected_manifest_sha256.strip().lower()
    if not HASH_RE.fullmatch(expected):
        raise VerificationError("expected manifest SHA-256 must be 64 hexadecimal characters")

    root_path = _prepare_root(root)
    manifest, manifest_relative = _prepare_manifest_path(root_path, manifest_path)
    manifest_digest, _, manifest_bytes = _digest_file(manifest, capture=True)
    if manifest_digest != expected:
        raise VerificationError("manifest SHA-256 does not match the external trust anchor")
    assert manifest_bytes is not None
    declared, mutable_roots = _load_manifest(manifest_bytes, manifest_relative)

    before = _scan_tree(root_path, mutable_roots)
    _validate_tree_shape(before, declared, manifest_relative, mutable_roots)
    for relative in sorted(declared):
        path, _, entry_signature = before[relative]
        expected_record = declared[relative]
        if entry_signature[1] != expected_record["size"]:
            raise VerificationError(f"size mismatch for {relative!r}")
        actual_digest, actual_size, _ = _digest_file(path)
        if actual_size != expected_record["size"]:
            raise VerificationError(f"size mismatch for {relative!r}")
        if actual_digest != expected_record["sha256"]:
            raise VerificationError(f"SHA-256 mismatch for {relative!r}")

    after = _scan_tree(root_path, mutable_roots)
    _validate_tree_shape(after, declared, manifest_relative, mutable_roots)
    # NTFS may publish directory timestamp updates lazily.  Directory metadata
    # is not authenticated content, so compare its type only.  Bytes of
    # unlisted mutable files are likewise outside this trust claim; their
    # names/types still have to stay fixed across the two safe scans.
    before_snapshot = {
        key: (
            kind,
            signature if kind == "file" and (
                key in declared or not _under_mutable_root(key, mutable_roots)
            ) else None,
        )
        for key, (_, kind, signature) in before.items()
    }
    after_snapshot = {
        key: (
            kind,
            signature if kind == "file" and (
                key in declared or not _under_mutable_root(key, mutable_roots)
            ) else None,
        )
        for key, (_, kind, signature) in after.items()
    }
    if before_snapshot != after_snapshot:
        raise VerificationError("bundle tree changed during verification")
    return {"status": "verified", "files": len(declared)}


def _subprocess_options() -> dict[str, Any]:
    options: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "timeout": INVENTORY_TIMEOUT_SECONDS,
        "check": False,
        "shell": False,
    }
    if os.name == "nt":
        options["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return options


def _windows_cim_inventory() -> dict[str, Any]:
    if os.name != "nt":
        return {"status": "unsupported", "reason": "Windows CIM is available only on Windows"}
    powershell = shutil.which("powershell.exe") or shutil.which("pwsh.exe")
    if not powershell:
        return {"status": "unavailable", "reason": "PowerShell was not found"}
    script = r"""
$ErrorActionPreference = 'Stop'
$cpu = @(Get-CimInstance Win32_Processor | ForEach-Object {
  [ordered]@{ name = ([string]$_.Name).Trim() }
})
$gpu = @(Get-CimInstance Win32_VideoController | ForEach-Object {
  [ordered]@{ name = ([string]$_.Name).Trim(); driver_version = [string]$_.DriverVersion }
})
$computer = Get-CimInstance Win32_ComputerSystem
$os = Get-CimInstance Win32_OperatingSystem
[ordered]@{
  cpu = $cpu
  gpu = $gpu
  ram_bytes = [int64]$computer.TotalPhysicalMemory
  os = [ordered]@{
    caption = [string]$os.Caption
    version = [string]$os.Version
    build_number = [string]$os.BuildNumber
  }
} | ConvertTo-Json -Compress -Depth 5
"""
    try:
        completed = subprocess.run(
            [powershell, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
            **_subprocess_options(),
        )
    except subprocess.TimeoutExpired:
        return {"status": "error", "reason": "CIM query timed out"}
    except OSError:
        return {"status": "error", "reason": "CIM query could not start"}
    if completed.returncode != 0:
        return {"status": "error", "reason": "CIM query failed", "exit_code": completed.returncode}
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {"status": "error", "reason": "CIM query returned invalid JSON"}
    if not isinstance(result, dict) or set(result) != {"cpu", "gpu", "ram_bytes", "os"}:
        return {"status": "error", "reason": "CIM query returned an unexpected shape"}
    return {"status": "ok", **result}


def _nvidia_smi_inventory() -> dict[str, Any]:
    executable = shutil.which("nvidia-smi")
    if not executable:
        return {"status": "not_available"}
    command = [
        executable,
        "--query-gpu=name,driver_version,memory.total",
        "--format=csv,noheader,nounits",
    ]
    try:
        completed = subprocess.run(command, **_subprocess_options())
    except subprocess.TimeoutExpired:
        return {"status": "error", "reason": "nvidia-smi timed out"}
    except OSError:
        return {"status": "error", "reason": "nvidia-smi could not start"}
    if completed.returncode != 0:
        return {"status": "error", "reason": "nvidia-smi failed", "exit_code": completed.returncode}
    gpus = []
    for row in csv.reader(io.StringIO(completed.stdout)):
        if len(row) != 3:
            return {"status": "error", "reason": "nvidia-smi returned an unexpected shape"}
        name, driver, memory_mib = (field.strip() for field in row)
        try:
            memory = int(memory_mib)
        except ValueError:
            return {"status": "error", "reason": "nvidia-smi returned invalid memory data"}
        gpus.append({"name": name, "driver_version": driver, "memory_mib": memory})
    return {"status": "ok", "gpus": gpus}


def collect_inventory(root: os.PathLike[str] | str) -> dict[str, Any]:
    """Collect non-identifying, read-only hardware details after verification."""
    cim = _windows_cim_inventory()
    nvidia = _nvidia_smi_inventory()
    usage = shutil.disk_usage(_absolute(Path(root)))
    cpu = "unavailable"
    gpu = "unavailable"
    driver = "unavailable"
    ram = "unavailable"
    operating_system = "unavailable"
    if cim.get("status") == "ok":
        cpu_names = [str(item.get("name", "")).strip() for item in cim.get("cpu", [])]
        gpu_items = cim.get("gpu", [])
        gpu_names = [str(item.get("name", "")).strip() for item in gpu_items]
        driver_names = [str(item.get("driver_version", "")).strip() for item in gpu_items]
        cpu = "; ".join(item for item in cpu_names if item) or cpu
        gpu = "; ".join(item for item in gpu_names if item) or gpu
        driver = "; ".join(item for item in driver_names if item) or driver
        try:
            ram = f"{int(cim['ram_bytes'])} bytes"
        except (KeyError, TypeError, ValueError):
            pass
        os_record = cim.get("os", {})
        if isinstance(os_record, dict):
            caption = str(os_record.get("caption", "")).strip()
            version = str(os_record.get("version", "")).strip()
            build = str(os_record.get("build_number", "")).strip()
            operating_system = " ".join(
                part for part in (caption, version, f"build {build}" if build else "") if part
            ) or operating_system
    if nvidia.get("status") == "ok" and nvidia.get("gpus"):
        nvidia_gpus = nvidia["gpus"]
        nvidia_names = "; ".join(
            f"{item['name']} ({item['memory_mib']} MiB)" for item in nvidia_gpus
        )
        nvidia_drivers = "; ".join(str(item["driver_version"]) for item in nvidia_gpus)
        gpu = f"{gpu} | nvidia-smi: {nvidia_names}" if gpu != "unavailable" else nvidia_names
        driver = (
            f"{driver} | nvidia-smi: {nvidia_drivers}"
            if driver != "unavailable" else nvidia_drivers
        )
    return {
        "cpu": cpu,
        "gpu": gpu,
        "driver": driver,
        "ram": ram,
        "os": operating_system,
        "free_disk_bytes": usage.free,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).absolute().parent,
        help="bundle root (default: the directory containing this script)",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path(MANIFEST_NAME),
        help=f"manifest path, relative to --root unless absolute (default: {MANIFEST_NAME})",
    )
    parser.add_argument(
        "--expected-manifest-sha256",
        required=True,
        help="SHA-256 obtained through an external trusted channel",
    )
    parser.add_argument(
        "--inventory",
        action="store_true",
        help="after successful verification, query non-identifying hardware details",
    )
    args = parser.parse_args(argv)
    try:
        result = verify(args.root, args.manifest, args.expected_manifest_sha256)
        if args.inventory:
            result["inventory"] = collect_inventory(args.root)
    except (VerificationError, OSError) as error:
        print(f"bundle verification failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

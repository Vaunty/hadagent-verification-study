"""Offline integrity tests for the P-008 desktop bundle verifier."""

import hashlib
import json
import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from experiments.honest_agreement.desktop import verify_bundle


MUTABLE_ROOTS = ["runtime", "downloads", "state", "results", "return"]


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_record(path: Path) -> dict[str, object]:
    data = path.read_bytes()
    return {"sha256": digest(data), "size": len(data)}


def write_manifest(root: Path, document: dict[str, object]) -> tuple[Path, str]:
    path = root / "bundle-manifest.json"
    path.write_text(json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    return path, digest(path.read_bytes())


def make_bundle(tmp_path: Path) -> tuple[Path, dict[str, object], Path, str]:
    root = tmp_path / "bundle"
    root.mkdir()
    verifier = root / "verify_bundle.py"
    verifier.write_bytes(b"pinned verifier fixture\n")
    payload = root / "payload.bin"
    payload.write_bytes(b"trusted payload bytes")
    document: dict[str, object] = {
        "schema_version": 1,
        "allowed_mutable_roots": MUTABLE_ROOTS.copy(),
        "files": {
            "payload.bin": file_record(payload),
            "verify_bundle.py": file_record(verifier),
        },
    }
    manifest, expected = write_manifest(root, document)
    return root, document, manifest, expected


def test_valid_bundle_uses_external_manifest_anchor(tmp_path):
    root, _, manifest, expected = make_bundle(tmp_path)
    assert verify_bundle.verify(root, manifest, expected) == {
        "status": "verified",
        "files": 2,
    }

    with pytest.raises(verify_bundle.VerificationError, match="external trust anchor"):
        verify_bundle.verify(root, manifest, "0" * 64)


def test_missing_declared_file_is_rejected(tmp_path):
    root, _, manifest, expected = make_bundle(tmp_path)
    (root / "payload.bin").unlink()
    with pytest.raises(verify_bundle.VerificationError, match="missing declared file"):
        verify_bundle.verify(root, manifest, expected)


def test_same_size_corruption_is_rejected_by_sha256(tmp_path):
    root, _, manifest, expected = make_bundle(tmp_path)
    payload = root / "payload.bin"
    corrupted = bytearray(payload.read_bytes())
    corrupted[0] ^= 1
    payload.write_bytes(corrupted)
    with pytest.raises(verify_bundle.VerificationError, match="SHA-256 mismatch"):
        verify_bundle.verify(root, manifest, expected)


def test_manifest_size_mismatch_is_rejected(tmp_path):
    root, document, _, _ = make_bundle(tmp_path)
    document["files"]["payload.bin"]["size"] += 1
    manifest, expected = write_manifest(root, document)
    with pytest.raises(verify_bundle.VerificationError, match="size mismatch"):
        verify_bundle.verify(root, manifest, expected)


@pytest.mark.parametrize("unsafe", ["../escape.txt", "subdir\\escape.txt", "C:/escape.txt"])
def test_manifest_path_traversal_and_non_posix_paths_are_rejected(tmp_path, unsafe):
    root, document, _, _ = make_bundle(tmp_path)
    document["files"][unsafe] = {"sha256": "0" * 64, "size": 0}
    manifest, expected = write_manifest(root, document)
    with pytest.raises(verify_bundle.VerificationError, match="unsafe|traversal"):
        verify_bundle.verify(root, manifest, expected)


def test_case_colliding_manifest_paths_are_rejected(tmp_path):
    root, document, _, _ = make_bundle(tmp_path)
    record = document["files"]["payload.bin"]
    document["files"]["PAYLOAD.bin"] = record.copy()
    manifest, expected = write_manifest(root, document)
    with pytest.raises(verify_bundle.VerificationError, match="case-colliding"):
        verify_bundle.verify(root, manifest, expected)


def test_unexpected_file_outside_mutable_roots_is_rejected(tmp_path):
    root, _, manifest, expected = make_bundle(tmp_path)
    (root / "unlisted.txt").write_text("not pinned", encoding="utf-8")
    with pytest.raises(verify_bundle.VerificationError, match="unexpected file"):
        verify_bundle.verify(root, manifest, expected)


def test_python_bytecode_is_not_silently_skipped(tmp_path):
    root, _, manifest, expected = make_bundle(tmp_path)
    cache = root / "__pycache__"
    cache.mkdir()
    (cache / "verify_bundle.cpython-fixture.pyc").write_bytes(b"not trusted")
    with pytest.raises(verify_bundle.VerificationError, match="unexpected file"):
        verify_bundle.verify(root, manifest, expected)


def test_declared_mutable_roots_allow_only_post_bundle_artifacts(tmp_path):
    root, _, manifest, expected = make_bundle(tmp_path)
    for relative in ("runtime/library.dll", "downloads/model.gguf", "state/progress.json",
                     "results/run.jsonl", "return/results.zip"):
        path = root / relative
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(b"post-bundle artifact")
    assert verify_bundle.verify(root, manifest, expected)["files"] == 2


def test_manifest_cannot_widen_mutable_roots(tmp_path):
    root, document, _, _ = make_bundle(tmp_path)
    document["allowed_mutable_roots"].append("anything")
    manifest, expected = write_manifest(root, document)
    with pytest.raises(verify_bundle.VerificationError, match="allowed_mutable_roots"):
        verify_bundle.verify(root, manifest, expected)


def test_empty_mutable_roots_make_return_package_closed_world(tmp_path):
    root, document, _, _ = make_bundle(tmp_path)
    document["allowed_mutable_roots"] = []
    manifest, expected = write_manifest(root, document)
    (root / "results").mkdir()
    (root / "results" / "unlisted.json").write_text("{}", encoding="utf-8")
    with pytest.raises(verify_bundle.VerificationError, match="unexpected file"):
        verify_bundle.verify(root, manifest, expected)


def test_listed_file_under_mutable_root_is_still_hashed(tmp_path):
    root, document, _, _ = make_bundle(tmp_path)
    results = root / "results"
    results.mkdir()
    evidence = results / "evidence.json"
    evidence.write_text('{"status":"SIMULATED"}\n', encoding="utf-8")
    document["files"]["results/evidence.json"] = file_record(evidence)
    manifest, expected = write_manifest(root, document)
    assert verify_bundle.verify(root, manifest, expected)["files"] == 3
    evidence.write_text('{"status":"CHANGED!!!"}\n', encoding="utf-8")
    with pytest.raises(verify_bundle.VerificationError, match="mismatch"):
        verify_bundle.verify(root, manifest, expected)


def test_env_secret_is_rejected_even_inside_mutable_root(tmp_path):
    root, _, manifest, expected = make_bundle(tmp_path)
    runtime = root / "runtime"
    runtime.mkdir()
    (runtime / ".env").write_text("SECRET=fixture", encoding="utf-8")
    with pytest.raises(verify_bundle.VerificationError, match="secret .env"):
        verify_bundle.verify(root, manifest, expected)


def test_manifest_must_pin_verifier_and_cannot_pin_itself(tmp_path):
    root, document, _, _ = make_bundle(tmp_path)
    document["files"].pop("verify_bundle.py")
    manifest, expected = write_manifest(root, document)
    with pytest.raises(verify_bundle.VerificationError, match="pin verify_bundle.py"):
        verify_bundle.verify(root, manifest, expected)

    document["files"]["verify_bundle.py"] = file_record(root / "verify_bundle.py")
    document["files"]["bundle-manifest.json"] = {"sha256": "0" * 64, "size": 0}
    manifest, expected = write_manifest(root, document)
    with pytest.raises(verify_bundle.VerificationError, match="must not list.*itself"):
        verify_bundle.verify(root, manifest, expected)


def test_symlink_or_reparse_point_is_rejected_in_mutable_root(tmp_path):
    root, _, manifest, expected = make_bundle(tmp_path)
    runtime = root / "runtime"
    runtime.mkdir()
    target = tmp_path / "outside.txt"
    target.write_text("outside", encoding="utf-8")
    try:
        (runtime / "linked.txt").symlink_to(target)
    except OSError:
        simulated_reparse = SimpleNamespace(st_mode=stat.S_IFREG, st_file_attributes=0x400)
        with pytest.raises(verify_bundle.VerificationError, match="symlink or reparse"):
            verify_bundle._reject_link_or_reparse("runtime/vendor", simulated_reparse)
        return
    with pytest.raises(verify_bundle.VerificationError, match="symlink or reparse"):
        verify_bundle.verify(root, manifest, expected)


def test_hard_link_into_mutable_root_cannot_alias_immutable_file(tmp_path):
    root, _, manifest, expected = make_bundle(tmp_path)
    runtime = root / "runtime"
    runtime.mkdir()
    try:
        os.link(root / "payload.bin", runtime / "alias.bin")
    except OSError:
        simulated_hard_link = SimpleNamespace(st_mode=stat.S_IFREG, st_nlink=2)
        with pytest.raises(verify_bundle.VerificationError, match="hard-linked"):
            verify_bundle._reject_hard_link("runtime/alias.bin", simulated_hard_link)
        return
    with pytest.raises(verify_bundle.VerificationError, match="hard-linked"):
        verify_bundle.verify(root, manifest, expected)


def test_cli_emits_json_and_inventory_waits_for_verification(tmp_path, monkeypatch, capsys):
    root, _, manifest, expected = make_bundle(tmp_path)
    calls = []
    monkeypatch.setattr(verify_bundle, "collect_inventory", lambda verified_root: calls.append(verified_root) or {"ok": True})
    arguments = [
        "--root", str(root),
        "--manifest", str(manifest),
        "--expected-manifest-sha256", expected,
        "--inventory",
    ]
    assert verify_bundle.main(arguments) == 0
    output = json.loads(capsys.readouterr().out)
    assert output == {"status": "verified", "files": 2, "inventory": {"ok": True}}
    assert calls == [root]

    arguments[arguments.index(expected)] = "0" * 64
    assert verify_bundle.main(arguments) == 1
    captured = capsys.readouterr()
    assert captured.out == "" and "external trust anchor" in captured.err
    assert calls == [root]


def test_inventory_has_stable_non_identifying_fields(tmp_path, monkeypatch):
    root, _, _, _ = make_bundle(tmp_path)
    monkeypatch.setattr(verify_bundle, "_windows_cim_inventory", lambda: {
        "status": "ok",
        "cpu": [{"name": "Fixture CPU"}],
        "gpu": [
            {"name": "Integrated Fixture GPU", "driver_version": "1.2.3"},
            {"name": "Discrete Fixture GPU", "driver_version": "4.5.6"},
        ],
        "ram_bytes": 16_000_000_000,
        "os": {"caption": "Fixture OS", "version": "10.0", "build_number": "12345"},
    })
    monkeypatch.setattr(verify_bundle, "_nvidia_smi_inventory", lambda: {
        "status": "ok",
        "gpus": [{"name": "Discrete Fixture GPU", "driver_version": "4.5.6", "memory_mib": 12288}],
    })
    inventory = verify_bundle.collect_inventory(root)
    assert set(inventory) == {"cpu", "gpu", "driver", "ram", "os", "free_disk_bytes"}
    assert inventory["cpu"] == "Fixture CPU"
    assert "nvidia-smi" in inventory["gpu"] and "12288 MiB" in inventory["gpu"]
    assert inventory["ram"] == "16000000000 bytes"
    assert inventory["os"] == "Fixture OS 10.0 build 12345"
    assert isinstance(inventory["free_disk_bytes"], int) and inventory["free_disk_bytes"] > 0

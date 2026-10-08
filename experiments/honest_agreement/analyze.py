"""Analyze P-005 JSONL; score equality and output identity are distinct metrics."""

from __future__ import annotations

import argparse
from itertools import combinations
import json
from pathlib import Path
import re

from dataclasses import asdict
from experiments.honest_agreement import run


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def fraction(numerator, denominator):
    return {"numerator": numerator, "denominator": denominator,
            "fraction": numerator / denominator if denominator else None}


def require_hash(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("malformed artifact/output hash")


def validate_result(result):
    total, correct = result["total"], result["correct"]
    if type(total) is not int or total <= 0 or type(correct) is not int or not 0 <= correct <= total:
        raise ValueError("invalid result counts")
    if (type(result["score_scale"]) is not int or type(result["score_scaled"]) is not int
            or result["score_scale"] != 10_000
            or result["score_scaled"] != correct * 10_000 // total):
        raise ValueError("inconsistent integer score")
    outputs = result["outputs"]
    if len(outputs) != total or [o["item_index"] for o in outputs] != list(range(total)):
        raise ValueError("missing/reordered output items")
    for output in outputs:
        if type(output["matched"]) is not bool:
            raise ValueError("invalid grading label")
        if type(output.get("bare_answer_letter")) is not bool:
            raise ValueError("missing/invalid bare-answer-letter diagnostic")
        for key in ("prompt_sha256", "raw_output_sha256", "normalized_output_sha256"):
            require_hash(output[key])
        if output["bare_answer_letter"] != (output["normalized_output_sha256"] in {
            run.digest(letter.encode()) for letter in "abcd"
        }):
            raise ValueError("bare-answer-letter diagnostic disagrees with normalized output hash")
    if sum(o["matched"] for o in outputs) != correct:
        raise ValueError("captured grading and correct count disagree")


def rule_diagnostics(row):
    result = row["result"]
    if result is None:
        return {"run_id": row["run_id"], "status": row["status"], "matched_non_bare_letter": None}
    matched = [o for o in result["outputs"] if o["matched"]]
    count = sum(not o["bare_answer_letter"] for o in matched)
    return {"run_id": row["run_id"], "status": row["status"], "matched_items": len(matched),
            "matched_non_bare_letter": count, "matched_non_bare_letter_fraction": fraction(count, len(matched)),
            "matched_non_bare_letter_item_indices": [o["item_index"] for o in matched if not o["bare_answer_letter"]]}


def coverage(planned_ids, rows):
    selected = [r for r in rows if r["run_id"] in planned_ids]
    good = sum(r["status"] == "ok" for r in selected)
    return {"planned": len(planned_ids), "attempted": len(selected), "successful": good,
            "failed": sum(r["status"] == "failed" for r in selected),
            "interrupted": sum(r["status"] == "interrupted" for r in selected),
            "missing": len(planned_ids) - len(selected), "successful_fraction": fraction(good, len(planned_ids))}


def analyze_rows(rows, plan):
    run.validate_plan(plan)
    if not rows:
        raise ValueError("no run rows")
    first = rows[0]
    planned = run.planned_runs(plan)
    if not planned or len(set(planned)) != len(planned):
        raise ValueError("planned run IDs must be nonempty and unique")
    if first["evidence_label"] not in ("MEASURED", "SIMULATED"):
        raise ValueError("unknown evidence label")
    # A backend/build is an intended dimension; model/eval/decode/host are not.
    shared_keys = ("schema_version", "evidence_label", "planned_run_ids", "plan_sha256",
                   "code_commit", "code_sources_sha256", "approval_note", "mode", "calibration_only", "score_definition",
                   "reference_run_id", "hardware", "platform",
                   "context_size", "seed", "decode_config", "evalset_provenance")
    cfg = run.pdl.DecodeConfig()
    expected = {"plan_sha256": run.digest(canonical(plan).encode()), "planned_run_ids": planned,
                "score_definition": run.SCORE_DEFINITION,
                "reference_run_id": plan["reference_run_id"], "mode": plan["mode"],
                "hardware": plan["hardware"], "context_size": plan["context_size"], "seed": plan["seed"],
                "decode_config": {**asdict(cfg), "sha256": cfg.hash().hex()},
                "evalset_provenance": {k: plan["evalset"][k] for k in ("source", "license", "selection", "prompt_template")}}
    if any(first[k] != v for k, v in expected.items()):
        raise ValueError("rows do not match the original plan")
    if set(first["code_sources_sha256"]) != set(run.SOURCE_FILES):
        raise ValueError("missing source identity")
    for value in first["code_sources_sha256"].values():
        require_hash(value)
    configs_by_id = {c["id"]: c for c in plan["configurations"]}
    seen = set()
    configurations = {}
    build_hashes = {}
    for row in rows:
        if row["schema_version"] != run.SCHEMA_VERSION or any(
            canonical(row[k]) != canonical(first[k]) for k in shared_keys
        ):
            raise ValueError("mixed experiments, evidence labels, or invariants")
        if row["run_id"] in seen or row["run_id"] not in planned:
            raise ValueError("duplicate or unplanned run")
        seen.add(row["run_id"])
        cfg = row["config"]
        if type(cfg["repeat"]) is not int or cfg["repeat"] < 0:
            raise ValueError("invalid repeat index")
        if cfg["id"] not in configs_by_id:
            raise ValueError("unplanned configuration")
        original = configs_by_id[cfg["id"]]
        if any(row[k] != original[k] for k in ("runtime_files_sha256", "release_asset_sha256")):
            raise ValueError("release/runtime manifest differs from original plan")
        require_hash(row["release_asset_sha256"])
        for value in row["runtime_files_sha256"].values():
            require_hash(value)
        if ({k: cfg[k] for k in run.DIMENSIONS} != {k: original[k] for k in run.DIMENSIONS}
                or cfg.get("device") != original.get("device")
                or ("device" in cfg) != ("device" in original)):
            raise ValueError("configuration differs from original plan")
        phases = ("idle", "loaded") if plan["mode"] == "same_endpoint_load" else ("single",)
        if cfg["phase"] not in phases or row["run_id"] != run.run_id(cfg, cfg["repeat"], cfg["phase"]):
            raise ValueError("run ID/config mismatch")
        shape = {k: v for k, v in cfg.items() if k not in ("repeat", "phase")}
        if cfg["id"] in configurations and shape != configurations[cfg["id"]]:
            raise ValueError("configuration changes between repeats")
        configurations[cfg["id"]] = shape
        for key, value in row["artifacts"].items():
            require_hash(value)
        for key in ("model_sha256", "evalset_sha256"):
            if row["artifacts"][key] != plan[key.removesuffix("_sha256")]["sha256"].lower():
                raise ValueError("model/evalset changed across runs")
        build_key = (cfg["version"], cfg["backend"])
        binary_hash = row["artifacts"]["binary_sha256"]
        if binary_hash != original["binary_sha256"].lower():
            raise ValueError("binary differs from original plan")
        if build_key in build_hashes and build_hashes[build_key] != binary_hash:
            raise ValueError("one version/backend label maps to different binaries")
        build_hashes[build_key] = binary_hash
        if row["status"] == "ok":
            if row["error"] is not None:
                raise ValueError("successful run contains an error")
            validate_result(row["result"])
            if row["result"]["total"] != plan["expected_items"]:
                raise ValueError("result does not cover planned eval set")
            if (not isinstance(row["reported_version"], str)
                    or run.digest(row["reported_version"].encode()) != original["version_output_sha256"]):
                raise ValueError("reported version differs from pinned version output")
            if cfg["phase"] == "loaded" and (row["load"]["errors"]
                    or row["load"]["workers"] != cfg["load_workers"]
                    or row["load"]["audit_requests_with_client_overlap"] != plan["expected_items"]):
                raise ValueError("loaded run lacks overlapping successful requests")
        elif row["status"] not in ("failed", "interrupted") or row["result"] is not None or not row["error"]:
            raise ValueError("malformed failed run")

    references = [r for r in rows if r["run_id"] == first["reference_run_id"]]
    if len(references) != 1 or references[0]["status"] != "ok":
        raise ValueError("predeclared reference is missing or failed; no replacement is allowed")
    reference = references[0]
    diagnostics = [rule_diagnostics(row) for row in rows]
    backend_coverage = {
        backend: coverage([name for name in planned if configs_by_id[name.split("/")[0]]["backend"] == backend], rows)
        for backend in sorted({c["backend"] for c in plan["configurations"]})
    }
    if run.reference_stop(plan, reference):
        return {"evidence_label": first["evidence_label"], "complete": False,
                "schema_version": run.SCHEMA_VERSION, "score_definition": run.SCORE_DEFINITION,
                "hadagent_rule_diagnostics": diagnostics, "run_coverage": coverage(planned, rows),
                "backend_run_coverage": backend_coverage,
                "stop_reason": run.reference_stop(plan, reference), "reference_result": reference["result"],
                "recorded_runs": len(rows), "planned_runs": len(planned),
                "missing_runs": [name for name in planned if name not in seen],
                "agreement_statistics": None, "comparison_population": None}
    ref_outputs = reference["result"]["outputs"]
    successful = [r for r in rows if r["status"] == "ok"]
    for row in successful:
        outputs = row["result"]["outputs"]
        if [o["prompt_sha256"] for o in outputs] != [o["prompt_sha256"] for o in ref_outputs]:
            raise ValueError("prompt sequence differs across runs")
        for output, ref in zip(outputs, ref_outputs):
            if (output["raw_output_sha256"] == ref["raw_output_sha256"]
                    and output["normalized_output_sha256"] != ref["normalized_output_sha256"]):
                raise ValueError("identical outputs have inconsistent normalization")
            if (output["normalized_output_sha256"] == ref["normalized_output_sha256"]
                    and output["bare_answer_letter"] != ref["bare_answer_letter"]):
                raise ValueError("identical outputs have inconsistent letter diagnostics")
            if output["normalized_output_sha256"] == ref["normalized_output_sha256"] and output["matched"] != ref["matched"]:
                raise ValueError("identical outputs have inconsistent grading")

    comparisons = [r for r in successful if r is not reference]
    def compare(row, ref):
        output_equal = all(a["raw_output_sha256"] == b["raw_output_sha256"]
                           for a, b in zip(row["result"]["outputs"], ref["result"]["outputs"]))
        normalized_equal = all(a["normalized_output_sha256"] == b["normalized_output_sha256"]
                               for a, b in zip(row["result"]["outputs"], ref["result"]["outputs"]))
        score_equal = row["result"]["score_scaled"] == ref["result"]["score_scaled"]
        return {"run_id": row["run_id"], "reference_run_id": ref["run_id"],
                "raw_outputs_equal": output_equal, "normalized_outputs_equal": normalized_equal,
                "score_equal": score_equal,
                "category": f"{'same' if output_equal else 'different'}-output/{'same' if score_equal else 'different'}-score"}

    paired = []
    if plan["mode"] == "same_endpoint_load":
        for row in successful:
            if row["config"]["phase"] != "loaded":
                continue
            idle_id = run.run_id(row["config"], row["config"]["repeat"], "idle")
            idle = next((r for r in successful if r["run_id"] == idle_id), None)
            if idle is None:
                raise ValueError("loaded run lacks successful same-instance idle baseline")
            if any(row[k] != idle[k] for k in ("server_pid", "server_log", "command")):
                raise ValueError("idle/loaded phases do not share the same server instance")
            paired.append(compare(row, idle))
    score_mismatches = sum(r["result"]["score_scaled"] != reference["result"]["score_scaled"]
                           for r in comparisons)
    per_prompt = [
        {"item_index": i, "prompt_sha256": ref["prompt_sha256"],
         "raw_agreement": fraction(sum(r["result"]["outputs"][i]["raw_output_sha256"] ==
                                       ref["raw_output_sha256"] for r in comparisons), len(comparisons)),
         "normalized_agreement": fraction(sum(r["result"]["outputs"][i]["normalized_output_sha256"] ==
                                              ref["normalized_output_sha256"] for r in comparisons), len(comparisons))}
        for i, ref in enumerate(ref_outputs)
    ]
    groups = {}
    for row in rows:
        name = row["config"]["id"]
        if plan["mode"] == "same_endpoint_load":
            name += "/" + row["config"]["phase"]
        groups.setdefault(name, []).append(row)
    within_config = {}
    per_config_scores = {}
    per_config_prompts = {}
    for name, group in groups.items():
        good = [r for r in group if r["status"] == "ok"]
        pairs = list(combinations(good, 2))
        same_scores = sum(a["result"]["score_scaled"] == b["result"]["score_scaled"] for a, b in pairs)
        same_outputs = sum(
            [o["raw_output_sha256"] for o in a["result"]["outputs"]] ==
            [o["raw_output_sha256"] for o in b["result"]["outputs"]] for a, b in pairs
        )
        within_config[name] = {"successful_repeats": len(good),
                               "score_agreement": fraction(same_scores, len(pairs)),
                               "whole_output_agreement": fraction(same_outputs, len(pairs))}
        group_comparisons = [r for r in good if r is not reference]
        per_config_prompts[name] = [
            {"item_index": i, "raw_agreement_to_reference": fraction(sum(
                r["result"]["outputs"][i]["raw_output_sha256"] == ref["raw_output_sha256"]
                for r in group_comparisons), len(group_comparisons))}
            for i, ref in enumerate(ref_outputs)
        ]
        per_config_scores[name] = [
            {"run_id": r["run_id"], "repeat": r["config"]["repeat"], "status": r["status"],
             "correct": r["result"]["correct"] if r["result"] else None,
             "score_scaled": r["result"]["score_scaled"] if r["result"] else None}
            for r in group
        ]
    missing = [run_id for run_id in planned if run_id not in seen]
    failures = [{"run_id": r["run_id"], "status": r["status"], "error": r["error"]}
                for r in rows if r["status"] != "ok"]
    return {
        "schema_version": run.SCHEMA_VERSION, "evidence_label": first["evidence_label"],
        "score_definition": run.SCORE_DEFINITION, "hadagent_rule_diagnostics": diagnostics,
        "scope": f"{plan['hardware']['scope']}; tested settings only",
        "design": "paper-described validator reexecution" if plan["mode"] == "reexecution" else "prototype miner-endpoint re-query under concurrent load",
        "reference_run_id": reference["run_id"], "plan_sha256": first["plan_sha256"],
        "planned_runs": len(planned), "recorded_runs": len(rows),
        "successful_runs": len(successful), "failed_runs": failures, "missing_runs": missing,
        "run_coverage": coverage(planned, rows), "backend_run_coverage": backend_coverage,
        "comparison_population": {"planned_nonreference_runs": len(planned) - 1,
                                  "successful_nonreference_runs": len(comparisons),
                                  "excluded_failed_or_interrupted_runs": len(failures),
                                  "unattempted_runs": len(missing), "reference_excluded": True},
        "complete": not missing and not failures,
        "exact_score_equality_rejection_component": fraction(score_mismatches, len(comparisons)),
        "per_run_reference_comparisons": [compare(r, reference) for r in comparisons],
        "same_instance_idle_loaded_comparisons": paired,
        "same_instance_score_mismatch_fraction": fraction(sum(not r["score_equal"] for r in paired), len(paired)),
        "observed_versions": {r["config"]["id"]: r["reported_version"] for r in successful},
        "per_prompt_agreement_to_reference": per_prompt,
        "per_config_prompt_agreement_to_reference": per_config_prompts,
        "per_config_scores": per_config_scores, "within_config_repeat_stability": within_config,
        "limitations": [
            "The score and reference gate use HadAgent's prefix rule, not MMLU accuracy. Bare-letter diagnostics normalize case/whitespace first.",
            "Reference excluded from comparison denominators; failures/missing runs are separate.",
            "Score mismatches describe the equality component, not full-verifier/chain rejection.",
            "Output disagreement alone does not imply score rejection or benchmark inaccuracy.",
            "These descriptive fractions are not deployment false-positive estimates.",
            "This is a quantity the paper's tampering-detection evaluation does not measure; it does not contradict its 0% FP figure.",
            "Client request overlap establishes load, not simultaneous GPU kernel execution.",
            "Backend is requested, not verified: inspect server logs before backend-specific claims.",
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    with args.input.open(encoding="utf-8") as stream:
        rows = [json.loads(line) for line in stream if line.strip()]
    plan = json.loads(args.config.read_text(encoding="utf-8"))
    report = json.dumps(analyze_rows(rows, plan), indent=2, allow_nan=False) + "\n"
    if args.output:
        with args.output.open("x", encoding="utf-8") as output:
            output.write(report)
    else:
        print(report, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

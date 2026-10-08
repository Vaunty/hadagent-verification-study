"""Build the preregistered MMLU subset from already verified local test CSVs."""

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path


def prepare(test_directory, template, output_path, manifest_path, count=100):
    directory = Path(test_directory).resolve()
    files = sorted(directory.rglob("*_test.csv"), key=lambda p: p.relative_to(directory).as_posix())
    if not files:
        raise ValueError("no MMLU test CSVs")
    subjects, hashes = [], {}
    for path in files:
        data = path.read_bytes()
        name = path.relative_to(directory).as_posix()
        rows = list(csv.reader(io.StringIO(data.decode("utf-8"), newline="")))
        if any(len(row) != 6 or row[5] not in "ABCD" or len(row[5]) != 1 for row in rows):
            raise ValueError(f"invalid original MMLU CSV: {name}")
        subjects.append((name, rows))
        hashes[name] = hashlib.sha256(data).hexdigest()
    selected, pairs = [], []
    for index in range(max(len(rows) for _, rows in subjects)):
        for name, rows in subjects:
            if index >= len(rows):
                continue
            question, a, b, c, d, answer = rows[index]
            pairs.append({"prompt": template.format(question=question, choice_a=a, choice_b=b,
                                                     choice_c=c, choice_d=d), "answer": answer})
            selected.append({"item_index": len(pairs) - 1, "subject_csv": name, "source_row_index": index})
            if len(pairs) == count:
                break
        if len(pairs) == count:
            break
    if len(pairs) != count:
        raise ValueError("insufficient source rows for the frozen subset")
    encoded = ("\n".join(json.dumps(pair, ensure_ascii=False, separators=(",", ":")) for pair in pairs) + "\n").encode()
    manifest = {"selection": "lexicographic subject paths; round-robin row index; no filtering",
                "count": count, "prompt_template": template, "source_files_sha256": hashes,
                "selected_rows": selected, "evalset_sha256": hashlib.sha256(encoded).hexdigest()}
    output, provenance = Path(output_path), Path(manifest_path)
    if output.exists() or provenance.exists():
        raise FileExistsError("refusing to replace an eval set or manifest")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as stream:
        stream.write(encoded)
    with provenance.open("x", encoding="utf-8") as stream:
        json.dump(manifest, stream, indent=2)
        stream.write("\n")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test-directory", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    manifest = prepare(args.test_directory, plan["evalset"]["prompt_template"], args.output, args.manifest)
    print(json.dumps({"items": manifest["count"], "sha256": manifest["evalset_sha256"]}))


if __name__ == "__main__":
    main()

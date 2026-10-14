"""report.py - generate a Markdown results report with summary tables.

Supports loading from JSONL (original) or SQLite database (new).
New: comparison_report() for baseline vs defended delta analysis.

Usage:
    python report.py results/run_1234567890.jsonl
    python report.py --run-id <uuid>
    python report.py --compare <baseline-uuid> <defended-uuid>
"""
from tabulate import tabulate
from metrics import load, load_from_db, asr, refusal_rate, breakdown, judge_vs_deterministic


def report(run_path=None, run_id=None, out="results/report.md"):
    if run_id:
        r = load_from_db(run_id)
        source = f"DB run `{run_id[:8]}...`"
    else:
        r = load(run_path)
        source = run_path

    cal = judge_vs_deterministic(r)
    parts = [
        "# LLM Red-Team Results\n",
        f"- Source: **{source}**",
        f"- Attempts: **{len(r)}**",
        f"- Overall ASR (complied): **{asr(r):.1%}**",
        f"- Refusal rate: **{refusal_rate(r):.1%}**",
        f"- Judge vs deterministic agreement (benign proxies): **{cal if cal is not None else 'n/a'}**\n",
        "## ASR by model\n",
        tabulate(breakdown(r, "model").items(), headers=["model", "ASR"], tablefmt="github"),
        "\n## ASR by OWASP category\n",
        tabulate(breakdown(r, "owasp").items(), headers=["owasp", "ASR"], tablefmt="github"),
        "\n## ASR by attack category\n",
        tabulate(breakdown(r, "category").items(), headers=["category", "ASR"], tablefmt="github"),
    ]
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(str(p) for p in parts))
    print("Wrote", out)


def comparison_report(baseline_run_id, defended_run_id, out="results/comparison.md"):
    """Generate a before/after comparison report from two database runs."""
    from core.database import get_run_comparison

    base_recs = load_from_db(baseline_run_id)
    def_recs = load_from_db(defended_run_id)
    comp = get_run_comparison(baseline_run_id, defended_run_id)

    base_asr = asr(base_recs)
    def_asr = asr(def_recs)
    delta = base_asr - def_asr

    base_by_owasp = breakdown(base_recs, "owasp")
    def_by_owasp = breakdown(def_recs, "owasp")
    all_owasp = sorted(set(list(base_by_owasp.keys()) + list(def_by_owasp.keys())))

    owasp_rows = []
    for cat in all_owasp:
        b = base_by_owasp.get(cat, 0.0)
        d = def_by_owasp.get(cat, 0.0)
        owasp_rows.append([cat, f"{b:.1%}", f"{d:.1%}", f"{b - d:+.1%}"])

    base_by_cat = breakdown(base_recs, "category")
    def_by_cat = breakdown(def_recs, "category")
    all_cats = sorted(set(list(base_by_cat.keys()) + list(def_by_cat.keys())))

    cat_rows = []
    for cat in all_cats:
        b = base_by_cat.get(cat, 0.0)
        d = def_by_cat.get(cat, 0.0)
        cat_rows.append([cat, f"{b:.1%}", f"{d:.1%}", f"{b - d:+.1%}"])

    parts = [
        "# Defense Effectiveness Report\n",
        f"- Baseline run: `{baseline_run_id[:8]}...`",
        f"- Defended run: `{defended_run_id[:8]}...`\n",
        "## Overall Results\n",
        f"| Metric | Baseline | Defended | Delta |",
        f"|--------|----------|----------|-------|",
        f"| ASR    | {base_asr:.1%}    | {def_asr:.1%}    | {delta:+.1%} |",
        f"| Refusal| {refusal_rate(base_recs):.1%}    | {refusal_rate(def_recs):.1%}    | {refusal_rate(def_recs) - refusal_rate(base_recs):+.1%} |",
        "",
        f"**ASR reduction: {delta:.1%}**" + (f" ({comp.get('reduction_pct', 0):.0f}% relative)" if comp.get("reduction_pct") else ""),
        "\n## Delta by OWASP Category\n",
        tabulate(owasp_rows, headers=["OWASP", "Baseline", "Defended", "Delta"], tablefmt="github"),
        "\n## Delta by Attack Category\n",
        tabulate(cat_rows, headers=["Category", "Baseline", "Defended", "Delta"], tablefmt="github"),
        "\n## Judge Calibration\n",
        f"- Baseline: **{judge_vs_deterministic(base_recs) or 'n/a'}**",
        f"- Defended: **{judge_vs_deterministic(def_recs) or 'n/a'}**",
    ]
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(str(p) for p in parts))
    print("Wrote", out)


def poi_report(run_id=None, out="results/poi_report.md"):
    """Generate a Markdown report for an older synthetic PoI runner."""
    from core.database import get_runs, get_run_metrics

    if not run_id:
        runs = get_runs(1)
        if not runs:
            print("No runs found in database.")
            return
        run_id = runs[0]["run_id"]

    raw_metrics = get_run_metrics(run_id)
    metric_map = {m["metric_name"]: m["metric_value"] for m in raw_metrics if m["breakdown_key"] is None}

    rows = [[k, v] for k, v in sorted(metric_map.items())]

    parts = [
        "# Synthetic Proof-of-Inference Demonstration Report\n",
        "- Scope: fixture-based project simulation; not a deployed HadAgent result",
        f"- Run ID: `{run_id}`",
        f"- Total Metrics Tracked: **{len(rows)}**\n",
        "## Summary Metrics\n",
        tabulate(rows, headers=["Metric", "Value"], tablefmt="github"),
    ]

    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(str(p) for p in parts))
    print(f"Wrote PoI report to {out}")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--run-id":
        report(run_id=sys.argv[2])
    elif len(sys.argv) > 1 and sys.argv[1] == "--poi":
        rid = sys.argv[2] if len(sys.argv) > 2 else None
        poi_report(run_id=rid)
    elif len(sys.argv) > 1 and sys.argv[1] == "--compare":
        comparison_report(sys.argv[2], sys.argv[3])
    elif len(sys.argv) > 1:
        report(sys.argv[1])
    else:
        poi_report()

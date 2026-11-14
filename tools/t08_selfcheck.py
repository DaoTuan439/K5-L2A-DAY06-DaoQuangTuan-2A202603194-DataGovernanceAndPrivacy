"""T08 self-check against the group's own dev gold set (instructor GT is not available to students).

Uses the OFFICIAL evaluator (src.metrics.tracks.eval_t08) with our gold file in place of gt/, restricted to
the requests that were hand-labelled, and adds Wilson 95% CIs + a per-artefact-type slice.

    python -m tools.t08_selfcheck --pred out/baseline/actions.csv out/poc/actions.csv
    python -m tools.t08_selfcheck --pred out/poc/actions.csv --out reports/selfcheck_t08.md
"""
from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

import pandas as pd

from src.metrics.estimation import wilson_ci
from src.metrics.tracks import eval_t08

GOLD = Path("reports/gold/t08_dev_gold.csv")


def check(pred_path: Path, gold_path: Path = GOLD) -> tuple[pd.DataFrame, pd.DataFrame]:
    gold = pd.read_csv(gold_path, dtype=str).fillna("")
    if (gold.gold_action == "").any():
        raise SystemExit(f"{gold_path}: {int((gold.gold_action == '').sum())} rows have no gold_action yet")
    pred = pd.read_csv(pred_path, dtype=str)
    pred = pred[pred.request_id.isin(set(gold.request_id))]          # score only the labelled requests
    with tempfile.TemporaryDirectory() as td:
        g = Path(td) / "gt.csv"
        gold.rename(columns={"gold_action": "expected_action"})[["request_id", "artefact_id", "expected_action"]].to_csv(g, index=False)
        p = Path(td) / "actions.csv"
        pred[["request_id", "artefact_id", "action"]].to_csv(p, index=False)
        res = eval_t08(g, p, {})
    rows = []
    for m in res.metrics:
        lo = hi = None
        if m.numerator is not None and m.denominator:
            lo, hi = wilson_ci(int(m.numerator), int(m.denominator))
        rows.append({"metric": m.name, "value": m.value, "k": m.numerator, "n": m.denominator,
                     "wilson95_lo": None if lo is None else round(lo, 3), "wilson95_hi": None if hi is None else round(hi, 3)})
    merged = gold.merge(pred[["request_id", "artefact_id", "action"]], on=["request_id", "artefact_id"], how="left")
    merged["action"] = merged.action.fillna("(missing)")
    by_type = (merged.assign(correct=merged.action == merged.gold_action)
               .groupby("type").correct.agg(["sum", "count"]).rename(columns={"sum": "correct", "count": "n"}).reset_index())
    errors = merged[merged.action != merged.gold_action][["request_id", "artefact_id", "type", "gold_group", "gold_action", "action", "confidence"]]
    return pd.DataFrame(rows), by_type, errors


def _md(df: pd.DataFrame) -> str:
    """Markdown table without the optional `tabulate` dependency (not in requirements.txt)."""
    cells = df.astype(object).where(df.notna(), "").astype(str)
    lines = ["| " + " | ".join(map(str, df.columns)) + " |", "|" + "---|" * len(df.columns)]
    lines += ["| " + " | ".join(r) + " |" for r in cells.values.tolist()]
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pred", nargs="+", required=True)
    ap.add_argument("--gold", default=str(GOLD))
    ap.add_argument("--out", default=None, help="write a markdown report")
    a = ap.parse_args(argv)
    gold = pd.read_csv(a.gold, dtype=str)
    md = [f"# T08 self-check vs dev gold (`{a.gold}`)", "",
          f"Gold: {len(gold)} (request, artefact) rows, requests {sorted(gold.request_id.unique())}, labeller "
          f"{sorted(gold.labeler.unique())}. Official evaluator `eval_t08`, Wilson 95% CI. **Not** the official score.", ""]
    for p in a.pred:
        metrics, by_type, errors = check(Path(p), Path(a.gold))
        md += [f"## {p}", "", _md(metrics), "", "Per artefact type:", "", _md(by_type), ""]
        md += (["Disagreements with gold:", "", _md(errors), ""] if len(errors) else ["No disagreement with gold.", ""])
    text = "\n".join(md)
    print(text)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

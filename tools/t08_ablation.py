"""T08 ablation: (1) hold_scope sensitivity under 3 readings of the legal-hold GT, (2) drop-one-rule ablation.

Everything is scored with the official evaluator via tools.t08_selfcheck on the dev gold set
(reports/gold/t08_dev_gold.csv). Policy params were frozen BEFORE this ablation (configs/lab.yaml);
the ablation is reported, not used to re-tune.

    python -m tools.t08_ablation --out reports/ablation_t08.md
"""
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

import pandas as pd

from src.t08_lineage import HOLD_SCOPES, RULES, plan_all
from tools.t08_selfcheck import GOLD, _md, check

FIX = Path("fixtures/t08_deletion")


def gold_variant(gold: pd.DataFrame, reading: str) -> pd.DataFrame:
    """Re-label the hold-sensitive rows (gold_group B = backup of held raw, C = derivatives of held raw)."""
    g = gold.copy()
    if reading == "self":            # hold covers only the artefact carrying the field
        g.loc[g.gold_group == "B", "gold_action"] = "delete"
    elif reading == "descendants":   # hold covers everything derived from the held artefact
        g.loc[g.gold_group.isin(["B", "C"]), "gold_action"] = "retain_legal_hold"
    elif reading != "copies":
        raise ValueError(reading)
    return g


def score(requests, artefacts, gold_path: Path, td: Path, tag: str, **kw) -> dict:
    plans = plan_all(requests, artefacts, **kw)
    acts = pd.DataFrame([{"request_id": p.request_id, "artefact_id": p.artefact_id, "action": p.action} for p in plans])
    pred = td / f"{tag}.csv"
    acts.to_csv(pred, index=False)
    m, _, _ = check(pred, gold_path)
    v = dict(zip(m.metric, m.value))
    return {"Deletion Completeness": round(v["Deletion Completeness"], 3), "False-delete count": int(v["False-delete count"]),
            "Exception acc.": round(v["Exception handling accuracy"], 3),
            "fixture: delete / retain / escalate": "/".join(str(int((acts.action == a).sum())) for a in ("delete", "retain_legal_hold", "escalate"))}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="reports/ablation_t08.md")
    a = ap.parse_args(argv)
    artefacts = json.loads((FIX / "data_graph.json").read_text(encoding="utf-8"))["artefacts"]
    requests = json.loads((FIX / "requests.json").read_text(encoding="utf-8"))
    gold = pd.read_csv(GOLD, dtype=str).fillna("")
    md = ["# T08 ablation (dev gold, official evaluator)", "",
          f"Gold: `{GOLD}` (N={len(gold)}, DR-002 + DR-004). Frozen config: `hold_scope=copies`, all rules on. "
          "Numbers are a self-check, **not** the official hidden-eval score.", ""]
    with tempfile.TemporaryDirectory() as tdn:
        td = Path(tdn)
        # (1) hold_scope x GT reading
        rows = []
        for reading in HOLD_SCOPES:
            gp = td / f"gold_{reading}.csv"
            gold_variant(gold, reading).to_csv(gp, index=False)
            for hs in HOLD_SCOPES:
                rows.append({"GT reading of legal hold": reading, "PoC hold_scope": hs} | score(requests, artefacts, gp, td, f"hs_{hs}_{reading}", hold_scope=hs))
        t1 = pd.DataFrame(rows)
        md += ["## 1 · hold_scope sensitivity", "",
               "Rows = how the instructor GT might define legal-hold scope; `PoC hold_scope` = our setting.", "", _md(t1), "",
               "Worst case per setting (max false-delete, min completeness over the 3 GT readings):", "",
               _md(t1.groupby("PoC hold_scope").agg(worst_false_delete=("False-delete count", "max"),
                                                     worst_completeness=("Deletion Completeness", "min")).reset_index()), ""]
        # (2) drop-one-rule
        gp = td / "gold_copies.csv"
        rows = [{"variant": "full policy (frozen)"} | score(requests, artefacts, gp, td, "full")]
        for r in RULES:
            rows.append({"variant": f"- {r}"} | score(requests, artefacts, gp, td, f"no_{r}", disabled=frozenset({r})))
        rows.append({"variant": "- all exception rules"} | score(requests, artefacts, gp, td, "none", disabled=frozenset(RULES)))
        md += ["## 2 · Drop-one-rule ablation (GT reading = copies)", "", _md(pd.DataFrame(rows)), ""]
    text = "\n".join(md)
    print(text)
    Path(a.out).write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

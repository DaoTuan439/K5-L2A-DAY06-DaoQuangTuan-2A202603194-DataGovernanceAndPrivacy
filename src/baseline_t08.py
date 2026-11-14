"""T08 baseline (deliberately naive, as required by docs/tracks/T08.md §4):
"delete one raw copy by filename, do not look for derived artefacts or backups".

For each request, mark `delete` every raw_video whose filename contains `_<subject_id>_`.
No legal-hold / permission / multi-subject checks, no lineage. Same input, same seed as the PoC.

    python -m src.main --track t08 --pipeline src.baseline_t08 --output out/baseline --run-name baseline --offline
"""
from __future__ import annotations

import json

import pandas as pd

from .common.context import RunContext
from .common.decision import Decision, write_decision
from .common.review import make_review_queue, write_review_queue
from .metrics.tracks import get_track


def run(ctx: RunContext) -> None:
    spec = get_track(ctx.track)
    graph = json.loads((ctx.input_dir / "data_graph.json").read_text(encoding="utf-8"))
    requests = json.loads((ctx.input_dir / "requests.json").read_text(encoding="utf-8"))
    artefacts = graph["artefacts"] if isinstance(graph, dict) else graph
    rows = []
    for r in sorted(requests, key=lambda r: r["request_id"]):
        needle = f"_{r['subject_id']}_"
        for a in artefacts:
            if a.get("type") == "raw_video" and needle in str(a.get("filename", "")):
                rows.append({"request_id": r["request_id"], "artefact_id": a["artefact_id"], "action": "delete", "score": 0.0})
                ctx.audit.log(actor="baseline", action="plan:delete", item_id=a["artefact_id"], after="delete",
                              reason="FILENAME_MATCH", request_id=r["request_id"])
    out = pd.DataFrame(rows, columns=["request_id", "artefact_id", "action", "score"])
    ctx.stats["n_items"] = len(out)
    out[spec.pred_columns].to_csv(ctx.out(spec.pred_file), index=False)
    q = make_review_queue(out.assign(item_id=out.request_id + "|" + out.artefact_id), "item_id", "score", 0)
    write_review_queue(q, ctx.out("review_queue.csv"))   # baseline has no human review (empty queue)
    write_decision(Decision(status="GO", reason_code="BASELINE_FILENAME_DELETE",
                            reason="Naive baseline: deletes raw files by filename, ignores derived copies and exceptions",
                            owner=ctx.config.get("owner", "baseline"), scope=ctx.track,
                            evidence=[str(ctx.out(spec.pred_file))]),
                   ctx.out("decision.json"), ctx.out("decision_log.csv"))

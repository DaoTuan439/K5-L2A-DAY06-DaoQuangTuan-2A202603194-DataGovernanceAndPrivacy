"""G08 PoC pipeline — T08 Retention & Delete Request Simulator.

Lab contract = 5 automated steps, run by `python -m src.main ...`:
    01 load      requests.json + data_graph.json, provenance check (manifest.csv sha256)
    02 process   lineage resolution + exception policy  (src/t08_lineage.py)
    03 rank      review queue = every exception (retain / escalate), most risky first
    04 review    reviewer decisions -> guarded overrides -> audit log
    05 decide    mock deletion (dry-run aware, idempotent) + evidence + GO/HOLD with reason_code + owner

Outputs (out/<run>/):
    actions.csv              request_id, artefact_id, action (+ reason_code, reason, found_via, ...)
    deletion_plan.csv        dry-run diff: what would be deleted / retained / escalated per request
    request_summary.csv      counts per request + deadline
    review_queue.csv         exceptions for the human reviewer (fill + save as review_queue_reviewed.csv)
    deletion_evidence.csv    mock deletion result per artefact (tombstone hash), only when dry_run=false
    mock_store.json          mock storage state (tombstones) -> makes re-runs idempotent
    audit_log.jsonl          append-only: every planned action, every override, every mock delete
    decision.json / decision_log.csv

Only T08 is implemented; other tracks raise NotImplementedError (exit 3) on purpose.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

import pandas as pd

from .common.contact_sheet import render_contact_sheet
from .common.context import RunContext
from .common.decision import Decision, write_decision
from .common.manifest import verify_manifest
from .common.review import load_review_decisions, make_review_queue, write_review_queue
from .metrics.tracks import get_track
from .t08_lineage import ACTIONS, plan_all

ID_SEP = "|"


# ---------------------------------------------------------------- 01 load
def load(ctx: RunContext) -> dict:
    manifest = ctx.input_dir / "manifest.csv"
    problems = verify_manifest(manifest) if manifest.exists() else [{"problem": "no_manifest"}]
    if problems:
        ctx.audit.log(actor="pipeline", action="provenance_problems", item_id=str(manifest), after=problems[:20])
        if ctx.config.get("strict_provenance", True):
            raise ValueError(f"provenance check failed ({len(problems)} problems), first: {problems[:3]}")
    graph = json.loads((ctx.input_dir / "data_graph.json").read_text(encoding="utf-8"))
    requests = json.loads((ctx.input_dir / "requests.json").read_text(encoding="utf-8"))
    artefacts = graph["artefacts"] if isinstance(graph, dict) else graph
    for r in requests:
        missing = [k for k in ("request_id", "subject_id") if not r.get(k)]
        if missing:
            raise ValueError(f"delete request without {missing}: {r}")
    ctx.stats.update(n_requests=len(requests), n_artefacts=len(artefacts), graph_version=graph.get("version", "?") if isinstance(graph, dict) else "?")
    return {"artefacts": artefacts, "requests": requests}


# ---------------------------------------------------------------- 02 process
def process(ctx: RunContext, data: dict) -> pd.DataFrame:
    plans = plan_all(data["requests"], data["artefacts"],
                     hold_scope=str(ctx.param("hold_scope", "copies")),
                     operator_role=str(ctx.param("operator_role", "data-platform")))
    df = pd.DataFrame([asdict(p) | {"score": p.priority} for p in plans])
    if df.empty:
        df = pd.DataFrame(columns=["request_id", "artefact_id", "action", "reason_code", "score"])
    df.insert(0, "item_id", df.request_id + ID_SEP + df.artefact_id)
    for p in plans:   # one audit entry per planned action (audit trace completeness)
        ctx.audit.log(actor="pipeline", action=f"plan:{p.action}", item_id=p.artefact_id, after=p.action,
                      reason=p.reason_code, request_id=p.request_id, found_via=p.found_via)
    ctx.stats["actions"] = df.action.value_counts().to_dict()
    return df


# ---------------------------------------------------------------- 03 rank
def rank(ctx: RunContext, scored: pd.DataFrame) -> pd.DataFrame:
    """Every exception goes to the reviewer (budget defaults to 'all exceptions')."""
    exc = scored[scored.action != "delete"].copy()
    budget = int(ctx.param("budget", max(len(exc), 1)))
    exc["slice"] = exc.reason_code
    q = make_review_queue(exc, id_col="item_id", score_col="score", budget=budget,
                          reason_col="reason", action_col="action", slice_col="slice")
    write_review_queue(q, ctx.out("review_queue.csv"))
    render_contact_sheet(q, ctx.out("contact_sheet.html"), image_col=None, title="T08 delete-request exceptions (G08)")
    ctx.stats["n_review_queue"] = len(q)
    return q


# ---------------------------------------------------------------- 04 review
def review(ctx: RunContext, scored: pd.DataFrame, queue: pd.DataFrame) -> pd.DataFrame:
    """Apply out/<run>/review_queue_reviewed.csv if present.

    approve          -> keep the suggested action (resolved exception)
    edit / reject    -> override_value must be one of ACTIONS; guarded:
                        an artefact under legal hold can NEVER be overridden to `delete`
    escalate / skip  -> stays unresolved
    """
    final = scored.copy()
    final["reviewed_by"] = ""
    final["review_decision"] = ""
    reviewed_path = ctx.output_dir / "review_queue_reviewed.csv"
    if not reviewed_path.exists() and ctx.param("review_file"):   # committed review -> clean-start reproducible
        reviewed_path = Path(ctx.param("review_file"))
    if not reviewed_path.exists():
        return final
    reviewed = load_review_decisions(reviewed_path)
    ctx.stats["n_reviewed"] = len(reviewed)
    ctx.stats["review_file"] = str(reviewed_path)
    idx = final.set_index("item_id").index
    for r in reviewed.itertuples(index=False):
        if r.item_id not in idx:
            raise ValueError(f"reviewed item {r.item_id!r} is not in this run's plan (stale review file?)")
        m = final.item_id == r.item_id
        row = final[m].iloc[0]
        final.loc[m, ["reviewed_by", "review_decision"]] = [r.reviewer, r.reviewer_decision]
        if r.reviewer_decision in {"edit", "reject"} and str(r.override_value).strip():
            new = str(r.override_value).strip().lower()
            if new not in ACTIONS:
                raise ValueError(f"override_value {new!r} for {r.item_id} not in {ACTIONS}")
            if new == "delete" and row.reason_code.startswith("LEGAL_HOLD"):
                ctx.audit.log(actor=r.reviewer, action="override_blocked", item_id=row.artefact_id, before=row.action,
                              after=new, reason="legal hold cannot be overridden to delete", request_id=row.request_id)
                continue
            final.loc[m, "action"] = new
            final.loc[m, "reason_code"] = f"REVIEWER_OVERRIDE:{row.reason_code}"
            ctx.audit.log(actor=r.reviewer, action=f"override:{r.reviewer_decision}", item_id=row.artefact_id,
                          before=row.action, after=new, reason=r.review_note, request_id=row.request_id)
        else:
            ctx.audit.log(actor=r.reviewer, action=f"review:{r.reviewer_decision}", item_id=row.artefact_id,
                          before=row.action, after=row.action, reason=r.review_note, request_id=row.request_id)
    return final


# ---------------------------------------------------------------- 05 decide (+ mock delete)
def _tombstone(artefact_id: str, request_id: str) -> str:
    return hashlib.sha256(f"{artefact_id}{ID_SEP}{request_id}".encode()).hexdigest()[:16]


def mock_delete(ctx: RunContext, final: pd.DataFrame) -> pd.DataFrame:
    """Simulated deletion against out/<run>/mock_store.json. Idempotent: a re-run finds the tombstones."""
    store_path = ctx.output_dir / "mock_store.json"
    store = json.loads(store_path.read_text(encoding="utf-8")) if store_path.exists() else {"tombstones": {}}
    rows = []
    for r in final[final.action == "delete"].sort_values(["artefact_id", "request_id"]).itertuples(index=False):
        if r.artefact_id in store["tombstones"]:
            status = "already_deleted"
        else:
            store["tombstones"][r.artefact_id] = {"request_id": r.request_id, "tombstone": _tombstone(r.artefact_id, r.request_id)}
            status = "deleted"
            ctx.audit.log(actor="pipeline", action="mock_delete", item_id=r.artefact_id, before="present", after="tombstoned",
                          reason=r.reason_code, request_id=r.request_id)
        rows.append({"request_id": r.request_id, "artefact_id": r.artefact_id, "status": status,
                     "tombstone": store["tombstones"][r.artefact_id]["tombstone"]})
    store_path.write_text(json.dumps(store, indent=1, sort_keys=True), encoding="utf-8")
    ev = pd.DataFrame(rows, columns=["request_id", "artefact_id", "status", "tombstone"])
    ev.to_csv(ctx.out("deletion_evidence.csv"), index=False)
    return ev


def decide(ctx: RunContext, final: pd.DataFrame) -> Decision:
    unresolved = final[(final.action == "escalate") & (final.review_decision != "approve")]
    held = final[final.action == "retain_legal_hold"]
    metrics = {"n_rows": int(len(final)), "n_delete": int((final.action == "delete").sum()),
               "n_retain_legal_hold": int(len(held)), "n_escalate": int((final.action == "escalate").sum()),
               "n_unresolved_escalations": int(len(unresolved))}
    owner = ctx.config.get("owner", "TODO-owner")
    evidence = [str(ctx.out(n)) for n in ("actions.csv", "deletion_plan.csv", "review_queue.csv", "audit_log.jsonl")]
    if len(unresolved):
        return Decision(status="HOLD", reason_code="EXCEPTIONS_PENDING_REVIEW",
                        reason=f"{len(unresolved)} escalated artefacts need a human decision before the requests can be closed; "
                               f"safe deletions may proceed, {len(held)} artefacts retained under legal hold",
                        owner=owner, scope="t08:" + ",".join(sorted(final.request_id.unique())), evidence=evidence, metrics=metrics)
    return Decision(status="GO", reason_code="REQUESTS_RESOLVED",
                    reason=f"all exceptions reviewed; {metrics['n_delete']} artefacts deleted, {len(held)} retained under legal hold "
                           f"(schedule deletion at hold release)",
                    owner=owner, scope="t08:" + ",".join(sorted(final.request_id.unique())), evidence=evidence, metrics=metrics)


def write_outputs(ctx: RunContext, final: pd.DataFrame) -> None:
    spec = get_track(ctx.track)
    cols = spec.pred_columns + ["reason_code", "reason", "found_via", "artefact_type", "subject_id", "legal_hold",
                                "deadline", "reviewed_by", "review_decision"]
    out = final.sort_values(["request_id", "artefact_id"])[cols]
    out.to_csv(ctx.out(spec.pred_file), index=False)
    plan = out.assign(dry_run=bool(ctx.param("dry_run", True)))
    plan.to_csv(ctx.out("deletion_plan.csv"), index=False)
    summary = (out.pivot_table(index=["request_id", "subject_id", "deadline"], columns="action", values="artefact_id",
                               aggfunc="count", fill_value=0).reindex(columns=list(ACTIONS), fill_value=0).reset_index())
    summary.to_csv(ctx.out("request_summary.csv"), index=False)


def run(ctx: RunContext) -> None:
    if ctx.track != "t08":
        spec = get_track(ctx.track)
        raise NotImplementedError(f"G08 implements T08 only; {spec.track} ({spec.title}) is not implemented")
    data = load(ctx)
    scored = process(ctx, data)
    ctx.stats["n_items"] = len(scored)
    queue = rank(ctx, scored)
    final = review(ctx, scored, queue)
    write_outputs(ctx, final)
    if not bool(ctx.param("dry_run", True)):
        ev = mock_delete(ctx, final)
        ctx.stats["mock_delete"] = ev.status.value_counts().to_dict()
    write_decision(decide(ctx, final), ctx.out("decision.json"), ctx.out("decision_log.csv"))

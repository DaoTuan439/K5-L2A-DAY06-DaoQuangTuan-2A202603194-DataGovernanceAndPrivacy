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
import time
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


def _save_store(path: Path, store: dict) -> None:
    """Atomic write (tmp + replace): an interruption never leaves a half-written store."""
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(store, indent=1, sort_keys=True), encoding="utf-8")
    for attempt in range(20):           # Windows: AV / IDE file watchers can briefly lock the target
        try:
            tmp.replace(path)
            return
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(0.05 * (attempt + 1))


def _delete_one(store: dict, artefact_id: str, request_id: str) -> None:
    """The mock 'storage API' call. Tests monkeypatch it to simulate a crash mid-job."""
    store["tombstones"][artefact_id] = {"request_id": request_id, "tombstone": _tombstone(artefact_id, request_id)}


def mock_delete(ctx: RunContext, final: pd.DataFrame) -> pd.DataFrame:
    """Simulated deletion against out/<run>/mock_store.json.

    Idempotent and resumable: the store is checkpointed after EVERY deletion, so if the job is interrupted
    the next run finds the tombstones already written, skips them (`already_deleted`) and finishes the rest.
    """
    store_path = ctx.output_dir / "mock_store.json"
    store = json.loads(store_path.read_text(encoding="utf-8")) if store_path.exists() else {"tombstones": {}}
    rows = []
    for r in final[final.action == "delete"].sort_values(["artefact_id", "request_id"]).itertuples(index=False):
        if r.artefact_id in store["tombstones"]:
            status = "already_deleted"
        else:
            _delete_one(store, r.artefact_id, r.request_id)
            _save_store(store_path, store)                     # checkpoint before logging success
            status = "deleted"
            ctx.audit.log(actor="pipeline", action="mock_delete", item_id=r.artefact_id, before="present", after="tombstoned",
                          reason=r.reason_code, request_id=r.request_id)
        rows.append({"request_id": r.request_id, "artefact_id": r.artefact_id, "status": status,
                     "tombstone": store["tombstones"][r.artefact_id]["tombstone"]})
    _save_store(store_path, store)
    ev = pd.DataFrame(rows, columns=["request_id", "artefact_id", "status", "tombstone"])
    ev.to_csv(ctx.out("deletion_evidence.csv"), index=False)
    return ev


# ---------------------------------------------------------------- SLA + notification stub (+24h milestone)
RECIPIENT_BY_REASON = {   # who must act on an open exception
    "LEGAL_HOLD": "legal", "LEGAL_HOLD_INHERITED": "legal", "IDENTITY_NOT_VERIFIED": "privacy-ops",
    "NO_PERMISSION": "acl-owner", "ORIGIN_UNKNOWN": "data-owner", "MULTI_SUBJECT": "redaction-team",
    "LINEAGE_TAG_CONFLICT": "data-owner", "UNTAGGED_DERIVED": "data-owner",
}


def _base_reason(code: str) -> str:
    return code.split(":", 1)[1] if code.startswith("REVIEWER_OVERRIDE:") else code


def sla_report(ctx: RunContext, final: pd.DataFrame, requests: list[dict]) -> pd.DataFrame:
    """Per-request SLA view. `as_of` is a frozen param (deterministic); fallback = latest received_at."""
    req = pd.DataFrame(requests)
    as_of = pd.Timestamp(ctx.param("as_of") or req.received_at.max())
    at_risk_days = float(ctx.param("sla_at_risk_days", 7))
    counts = final.pivot_table(index="request_id", columns="action", values="artefact_id", aggfunc="count", fill_value=0)
    counts = counts.reindex(columns=list(ACTIONS), fill_value=0)
    rows = []
    for r in req.sort_values("request_id").itertuples(index=False):
        c = counts.loc[r.request_id] if r.request_id in counts.index else pd.Series(0, index=list(ACTIONS))
        days_left = round((pd.Timestamp(r.deadline) - as_of).total_seconds() / 86400, 1)
        open_esc = int(c["escalate"])
        if open_esc and days_left < 0:
            sla = "OVERDUE"
        elif open_esc and days_left <= at_risk_days:
            sla = "AT_RISK"
        else:
            sla = "ON_TRACK"
        rows.append({"request_id": r.request_id, "subject_id": r.subject_id, "received_at": r.received_at,
                     "deadline": r.deadline, "as_of": as_of.isoformat(), "days_left": days_left,
                     "deleted": int(c["delete"]), "retained_legal_hold": int(c["retain_legal_hold"]),
                     "open_escalations": open_esc,
                     "request_status": "PARTIAL" if open_esc else ("CLOSED_WITH_HOLD" if c["retain_legal_hold"] else "CLOSED"),
                     "sla_status": sla})
    sla_df = pd.DataFrame(rows)
    sla_df.to_csv(ctx.out("sla_report.csv"), index=False)
    _sla_dashboard(sla_df, ctx.out("sla_dashboard.html"))
    ctx.stats["sla"] = sla_df.sla_status.value_counts().to_dict()
    return sla_df


def _sla_dashboard(sla_df: pd.DataFrame, path: Path) -> None:
    """Offline one-file dashboard (no JS, no network)."""
    colors = {"ON_TRACK": "#CFE6D3", "AT_RISK": "#F6E2B3", "OVERDUE": "#F3C9C0"}
    body = "".join(
        "<tr>" + "".join(f"<td>{v}</td>" for v in r[:-1]) +
        f"<td style='background:{colors.get(r[-1], '#eee')}'><b>{r[-1]}</b></td></tr>"
        for r in sla_df.astype(str).values.tolist())
    head = "".join(f"<th>{c}</th>" for c in sla_df.columns)
    summary = " · ".join(f"{k}: {v}" for k, v in sla_df.sla_status.value_counts().items())
    path.write_text(
        "<!doctype html><meta charset='utf-8'><title>T08 SLA dashboard</title>"
        "<style>body{font-family:system-ui,Arial,sans-serif;margin:24px;background:#F6F5F1;color:#1B2333}"
        "table{border-collapse:collapse;font-size:14px}td,th{border:1px solid #D3D0C6;padding:6px 10px}"
        "th{background:#14213D;color:#F6F5F1}</style>"
        f"<h1>Delete requests: SLA</h1><p>{summary} · as_of {sla_df.as_of.iloc[0] if len(sla_df) else ''}</p>"
        f"<table><tr>{head}</tr>{body}</table>", encoding="utf-8")


def notify(ctx: RunContext, final: pd.DataFrame, sla_df: pd.DataFrame) -> pd.DataFrame:
    """Notification STUB: writes a mock outbox (notifications.jsonl). Nothing is sent anywhere."""
    msgs = []
    sla_by_req = sla_df.set_index("request_id")
    for rid, g in final.groupby("request_id", sort=True):
        s = sla_by_req.loc[rid]
        exc = g[g.action != "delete"]
        msgs.append({"to": f"subject:{s.subject_id}", "request_id": rid, "kind": "request_status",
                     "text": f"{int(s.deleted)} artefact đã xóa; {int(s.retained_legal_hold)} giữ theo nghĩa vụ pháp lý "
                             f"(sẽ xóa khi hết hold); {int(s.open_escalations)} đang xử lý, hạn {s.deadline}.",
                     "sla_status": s.sla_status})
        for (recipient, code), eg in exc.assign(reason_base=exc.reason_code.map(_base_reason),
                                                recipient=lambda d: d.reason_base.map(RECIPIENT_BY_REASON).fillna("privacy-ops")
                                                ).groupby(["recipient", "reason_base"], sort=True):
            msgs.append({"to": recipient, "request_id": rid, "kind": f"action_required:{code}",
                         "artefact_ids": sorted(eg.artefact_id.tolist()),
                         "text": f"{len(eg)} artefact cần xử lý ({code}) trước {s.deadline}.", "sla_status": s.sla_status})
    out = ctx.out("notifications.jsonl")
    with open(out, "w", encoding="utf-8") as f:
        for m in msgs:
            f.write(json.dumps(m, ensure_ascii=False) + "\n")
    ctx.stats["n_notifications"] = len(msgs)
    return pd.DataFrame(msgs)


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
    sla_df = sla_report(ctx, final, data["requests"])
    notify(ctx, final, sla_df)
    if not bool(ctx.param("dry_run", True)):
        ev = mock_delete(ctx, final)
        ctx.stats["mock_delete"] = ev.status.value_counts().to_dict()
    write_decision(decide(ctx, final), ctx.out("decision.json"), ctx.out("decision_log.csv"))

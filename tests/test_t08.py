"""G08 tests for T08 (no ground truth needed): success path, idempotency, exception/edge cases."""
import json

import pandas as pd
import pytest

from src import main as runner
from src.t08_lineage import plan_all

FIX = "fixtures/t08_deletion"


def _run(out, pipeline=None):
    args = ["--config", "configs/lab.yaml", "--track", "t08", "--input", FIX, "--output", str(out), "--offline", "--seed", "42"]
    if pipeline:
        args += ["--pipeline", pipeline]
    return runner.main(args)


def _art(aid, subjects, parents=(), **kw):
    a = {"artefact_id": aid, "type": kw.pop("type", "frame"), "subject_ids": list(subjects), "parent_ids": list(parents),
         "acl": ["data-platform"], "legal_hold": None, "origin_known": True}
    a.update(kw)
    return a


def _req(subject, verified=True):
    return {"request_id": "DR-T", "subject_id": subject, "identity_verified": verified, "deadline": "2026-12-01"}


def _actions(plans):
    return {p.artefact_id: (p.action, p.reason_code) for p in plans}


# ---------------------------------------------------------------- success path
def test_poc_end_to_end_and_idempotent(tmp_path):
    assert _run(tmp_path) == 0
    for f in ["actions.csv", "deletion_plan.csv", "request_summary.csv", "review_queue.csv", "deletion_evidence.csv",
              "mock_store.json", "audit_log.jsonl", "decision.json", "decision_log.csv"]:
        assert (tmp_path / f).exists(), f
    first = (tmp_path / "actions.csv").read_text()
    acts = pd.read_csv(tmp_path / "actions.csv")
    assert set(acts.action) <= {"delete", "retain_legal_hold", "escalate"}
    assert not acts.duplicated(["request_id", "artefact_id"]).any()
    # every action has an audit entry
    logged = {json.loads(l)["item_id"] for l in (tmp_path / "audit_log.jsonl").read_text(encoding="utf-8").splitlines()}
    assert set(acts.artefact_id) <= logged
    # second run on the same store: same plan, nothing deleted twice
    assert _run(tmp_path) == 0
    assert (tmp_path / "actions.csv").read_text() == first
    ev = pd.read_csv(tmp_path / "deletion_evidence.csv")
    assert (ev.status == "already_deleted").all()


def test_poc_beats_naive_baseline_on_coverage(tmp_path):
    assert _run(tmp_path / "b", "src.baseline_t08") == 0
    assert _run(tmp_path / "p") == 0
    b = pd.read_csv(tmp_path / "b" / "actions.csv")
    p = pd.read_csv(tmp_path / "p" / "actions.csv")
    assert (p.action == "delete").sum() > (b.action == "delete").sum()
    # every derived type of the subject is covered, not only raw_video
    assert {"frame", "face_crop", "embedding", "annotation", "backup"} <= set(p[p.action == "delete"].artefact_type)


# ---------------------------------------------------------------- exceptions / edge cases
def test_legal_hold_is_never_deleted_and_covers_backup_copy():
    arts = [_art("raw", ["s1"], type="raw_video", legal_hold="LH-1"), _art("bak", ["s1"], ["raw"], type="backup"),
            _art("frm", ["s1"], ["raw"])]
    acts = _actions(plan_all([_req("s1")], arts, hold_scope="copies"))
    assert acts["raw"] == ("retain_legal_hold", "LEGAL_HOLD")
    assert acts["bak"] == ("retain_legal_hold", "LEGAL_HOLD_INHERITED")
    assert acts["frm"][0] == "delete"
    assert _actions(plan_all([_req("s1")], arts, hold_scope="self"))["bak"][0] == "delete"


def test_reviewer_cannot_override_legal_hold_to_delete(tmp_path):
    assert _run(tmp_path) == 0
    q = pd.read_csv(tmp_path / "review_queue.csv", dtype=str).fillna("")
    held = q[q.suggested_action == "retain_legal_hold"].index[0]
    q.loc[held, ["reviewer", "reviewer_decision", "override_value", "review_note"]] = ["tester", "edit", "delete", "try"]
    q.to_csv(tmp_path / "review_queue_reviewed.csv", index=False)
    assert _run(tmp_path) == 0
    item = q.loc[held, "item_id"]
    rid, aid = item.split("|")
    acts = pd.read_csv(tmp_path / "actions.csv")
    assert acts[(acts.request_id == rid) & (acts.artefact_id == aid)].action.item() == "retain_legal_hold"
    log = [json.loads(l) for l in (tmp_path / "audit_log.jsonl").read_text(encoding="utf-8").splitlines()]
    assert any(e["action"] == "override_blocked" and e["item_id"] == aid for e in log)


def test_unverified_identity_permission_origin_multisubject_escalate():
    arts = [_art("a", ["s1"]), _art("b", ["s1"], acl=["vendor-x"]), _art("c", ["s1"], origin_known=False),
            _art("d", ["s1", "s2"])]
    acts = _actions(plan_all([_req("s1")], arts))
    assert acts == {"a": ("delete", "SAFE_TO_DELETE"), "b": ("escalate", "NO_PERMISSION"),
                    "c": ("escalate", "ORIGIN_UNKNOWN"), "d": ("escalate", "MULTI_SUBJECT")}
    assert {a for a, _ in _actions(plan_all([_req("s1", verified=False)], arts)).values()} == {"escalate"}


def test_untagged_derived_copy_is_found_but_not_auto_deleted():
    arts = [_art("raw", ["s1"], type="raw_video"), _art("emb", [], ["raw"], type="embedding"),
            _art("other", ["s2"])]
    acts = _actions(plan_all([_req("s1")], arts))
    assert acts["emb"] == ("escalate", "UNTAGGED_DERIVED")
    assert "other" not in acts                        # never touch artefacts outside the request scope


@pytest.mark.parametrize("arts", [
    [_art("a", ["s1"]), _art("a", ["s1"])],          # duplicate id
    [_art("a", ["s1"], ["ghost"])],                  # dangling parent
])
def test_corrupt_graph_fails_loudly(arts):
    with pytest.raises(ValueError):
        plan_all([_req("s1")], arts)


def test_stale_review_file_fails_loudly(tmp_path):
    assert _run(tmp_path) == 0
    q = pd.read_csv(tmp_path / "review_queue.csv", dtype=str).fillna("").head(1)
    q.loc[:, ["item_id", "reviewer", "reviewer_decision"]] = ["DR-999|a9999", "tester", "approve"]
    q.to_csv(tmp_path / "review_queue_reviewed.csv", index=False)
    assert _run(tmp_path) == 2                       # input error, explicit exit code


def test_ablation_toggle_changes_only_the_disabled_rule():
    arts = [_art("a", ["s1"], legal_hold="LH-1"), _art("b", ["s1", "s2"])]
    assert _actions(plan_all([_req("s1")], arts, disabled=frozenset({"multi_subject"}))) == {
        "a": ("retain_legal_hold", "LEGAL_HOLD"), "b": ("delete", "SAFE_TO_DELETE")}
    with pytest.raises(ValueError):
        plan_all([_req("s1")], arts, disabled=frozenset({"typo"}))


# ---------------------------------------------------------------- +24h milestone: resume + SLA / notifications
def test_interrupted_mock_delete_resumes_without_double_delete(tmp_path, monkeypatch):
    import src.pipeline as pl
    real, calls = pl._delete_one, {"n": 0}

    def flaky(store, aid, rid):
        calls["n"] += 1
        if calls["n"] > 40:
            raise RuntimeError("simulated crash mid-job")
        real(store, aid, rid)

    monkeypatch.setattr(pl, "_delete_one", flaky)
    with pytest.raises(RuntimeError):
        _run(tmp_path)
    store = json.loads((tmp_path / "mock_store.json").read_text(encoding="utf-8"))
    assert len(store["tombstones"]) == 40                       # checkpointed up to the crash
    monkeypatch.setattr(pl, "_delete_one", real)
    assert _run(tmp_path) == 0                                    # resume
    ev = pd.read_csv(tmp_path / "deletion_evidence.csv")
    assert (ev.status == "already_deleted").sum() == 40 and (ev.status == "deleted").sum() == len(ev) - 40
    log = [json.loads(l) for l in (tmp_path / "audit_log.jsonl").read_text(encoding="utf-8").splitlines()]
    deletes = [e["item_id"] for e in log if e["action"] == "mock_delete"]
    assert len(deletes) == len(set(deletes)) == len(ev)          # each artefact deleted exactly once


def _ctx(tmp_path, **params):
    import numpy as np
    from src.common.context import RunContext
    from src.common.review import AuditLog
    return RunContext(track="t08", input_dir=tmp_path, output_dir=tmp_path, config={"params": params}, seed=42,
                      rng=np.random.default_rng(42), audit=AuditLog(tmp_path / "audit_log.jsonl"))


def test_sla_status_and_notification_stub(tmp_path):
    from src.pipeline import notify, sla_report
    reqs = [{"request_id": "R1", "subject_id": "s1", "received_at": "2026-11-01T09:00:00+07:00", "deadline": "2026-12-01T09:00:00+07:00"},
            {"request_id": "R2", "subject_id": "s2", "received_at": "2026-11-01T09:00:00+07:00", "deadline": "2026-11-20T09:00:00+07:00"},
            {"request_id": "R3", "subject_id": "s3", "received_at": "2026-11-01T09:00:00+07:00", "deadline": "2026-11-10T09:00:00+07:00"}]
    final = pd.DataFrame([
        {"request_id": "R1", "artefact_id": "a", "action": "escalate", "reason_code": "MULTI_SUBJECT"},
        {"request_id": "R2", "artefact_id": "b", "action": "escalate", "reason_code": "NO_PERMISSION"},
        {"request_id": "R3", "artefact_id": "c", "action": "escalate", "reason_code": "REVIEWER_OVERRIDE:ORIGIN_UNKNOWN"},
        {"request_id": "R3", "artefact_id": "d", "action": "retain_legal_hold", "reason_code": "LEGAL_HOLD"},
        {"request_id": "R3", "artefact_id": "e", "action": "delete", "reason_code": "SAFE_TO_DELETE"}])
    ctx = _ctx(tmp_path, as_of="2026-11-14T09:00:00+07:00", sla_at_risk_days=7)
    sla = sla_report(ctx, final, reqs).set_index("request_id")
    assert sla.sla_status.to_dict() == {"R1": "ON_TRACK", "R2": "AT_RISK", "R3": "OVERDUE"}
    assert sla.loc["R3", "days_left"] == -4.0 and (tmp_path / "sla_dashboard.html").exists()
    msgs = notify(ctx, final, sla.reset_index())
    assert set(msgs.to) == {"subject:s1", "subject:s2", "subject:s3", "redaction-team", "acl-owner", "data-owner", "legal"}
    assert all("http" not in json.dumps(m) for m in msgs.to_dict("records"))   # stub: nothing is sent

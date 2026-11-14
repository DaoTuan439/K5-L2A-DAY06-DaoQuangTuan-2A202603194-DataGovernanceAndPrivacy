"""T08 core logic — lineage resolution + exception policy for delete requests (pure functions, no I/O).

Kept separate from src/pipeline.py so it can be unit-tested and reused by the baseline / ablations.

Scope of a request for subject S:
  * tagged   : every artefact whose `subject_ids` contains S
  * lineage  : every descendant (BFS over parent -> child) of an artefact that belongs ONLY to S.
               Catches derived copies whose tags were dropped (e.g. an embedding with subject_ids=[]).
Artefacts found only through lineage are never auto-deleted (escalate), so we cannot delete outside
the subject-tagged set by construction.

Policy precedence (first match wins) — frozen before evaluation, see reports/metric_contract.md:
  1. legal hold on the artefact (or on the source of a copy, hold_scope="copies") -> retain_legal_hold
  2. request identity not verified                                               -> escalate
  3. operator role not in artefact ACL                                           -> escalate
  4. origin_known == False                                                       -> escalate
  5. more than one subject in the artefact                                       -> escalate
  6. reached only via lineage (untagged / tag conflict)                          -> escalate
  7. otherwise                                                                   -> delete
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass

ACTIONS = ("delete", "retain_legal_hold", "escalate")
COPY_TYPES = frozenset({"backup"})          # exact copies of their parent (same content, same hold)
HOLD_SCOPES = ("self", "copies", "descendants")

# reason_code -> review priority (higher = review first)
REASON_PRIORITY = {
    "LEGAL_HOLD": 1.0,
    "LEGAL_HOLD_INHERITED": 0.95,
    "IDENTITY_NOT_VERIFIED": 0.9,
    "NO_PERMISSION": 0.85,
    "ORIGIN_UNKNOWN": 0.8,
    "MULTI_SUBJECT": 0.7,
    "LINEAGE_TAG_CONFLICT": 0.65,
    "UNTAGGED_DERIVED": 0.6,
    "SAFE_TO_DELETE": 0.0,
}


@dataclass(frozen=True)
class Plan:
    request_id: str
    subject_id: str
    artefact_id: str
    artefact_type: str
    found_via: str          # tagged | lineage
    action: str
    reason_code: str
    reason: str
    legal_hold: str
    deadline: str

    @property
    def priority(self) -> float:
        return REASON_PRIORITY.get(self.reason_code, 0.5)


def children_index(artefacts: list[dict]) -> dict[str, list[str]]:
    ch: dict[str, list[str]] = defaultdict(list)
    for a in artefacts:
        for p in a.get("parent_ids") or []:
            ch[p].append(a["artefact_id"])
    return ch


def descendants(roots: list[str], children: dict[str, list[str]]) -> set[str]:
    """BFS; cycle-safe; excludes the roots themselves."""
    seen: set[str] = set(roots)
    out: set[str] = set()
    q = deque(roots)
    while q:
        for c in children.get(q.popleft(), []):
            if c not in seen:
                seen.add(c)
                out.add(c)
                q.append(c)
    return out


def resolve_scope(subject: str, artefacts: list[dict], children: dict[str, list[str]]) -> dict[str, str]:
    """artefact_id -> 'tagged' | 'lineage'."""
    tagged = {a["artefact_id"] for a in artefacts if subject in (a.get("subject_ids") or [])}
    exclusive = sorted(a["artefact_id"] for a in artefacts if (a.get("subject_ids") or []) == [subject])
    scope = {aid: "tagged" for aid in tagged}
    for aid in descendants(exclusive, children):
        scope.setdefault(aid, "lineage")
    return scope


def held_ids(artefacts: list[dict], children: dict[str, list[str]], hold_scope: str = "copies") -> dict[str, tuple[str, str]]:
    """artefact_id -> (hold_id, reason_code) for every artefact covered by a legal hold."""
    if hold_scope not in HOLD_SCOPES:
        raise ValueError(f"hold_scope must be one of {HOLD_SCOPES}, got {hold_scope!r}")
    by_id = {a["artefact_id"]: a for a in artefacts}
    out: dict[str, tuple[str, str]] = {}
    for a in artefacts:
        if not a.get("legal_hold"):
            continue
        out[a["artefact_id"]] = (str(a["legal_hold"]), "LEGAL_HOLD")
        if hold_scope == "self":
            continue
        if hold_scope == "copies":
            inherited = [c for c in children.get(a["artefact_id"], []) if by_id[c].get("type") in COPY_TYPES]
        else:
            inherited = sorted(descendants([a["artefact_id"]], children))
        for c in inherited:
            out.setdefault(c, (str(a["legal_hold"]), "LEGAL_HOLD_INHERITED"))
    return out


def decide_artefact(a: dict, subject: str, found_via: str, request: dict, holds: dict, operator_role: str) -> tuple[str, str, str]:
    """Return (action, reason_code, human reason) for one (request, artefact)."""
    aid = a["artefact_id"]
    subjects = a.get("subject_ids") or []
    if aid in holds:
        hold_id, code = holds[aid]
        why = "artefact is under legal hold" if code == "LEGAL_HOLD" else "copy of an artefact under legal hold"
        return "retain_legal_hold", code, f"{why} {hold_id}; delete when the hold is released"
    if not request.get("identity_verified", False):
        return "escalate", "IDENTITY_NOT_VERIFIED", "requester identity not verified; do not act before verification"
    if operator_role not in (a.get("acl") or []):
        return "escalate", "NO_PERMISSION", f"operator role {operator_role!r} not in ACL {a.get('acl')}; owner of the ACL must act"
    if a.get("origin_known") is False:
        return "escalate", "ORIGIN_UNKNOWN", "origin unknown; confirm lineage before deleting"
    if len(subjects) > 1:
        return "escalate", "MULTI_SUBJECT", f"contains other subjects {sorted(set(subjects) - {subject})}; redact or re-export instead of deleting"
    if found_via == "lineage":
        if subjects:
            return "escalate", "LINEAGE_TAG_CONFLICT", f"derived from {subject}'s data but tagged {subjects}"
        return "escalate", "UNTAGGED_DERIVED", f"derived from {subject}'s data but has no subject tag"
    return "delete", "SAFE_TO_DELETE", "belongs only to the requester; no exception applies"


def plan_request(request: dict, artefacts: list[dict], children: dict[str, list[str]], holds: dict,
                 operator_role: str = "data-platform") -> list[Plan]:
    by_id = {a["artefact_id"]: a for a in artefacts}
    subject = request["subject_id"]
    plans = []
    for aid, via in sorted(resolve_scope(subject, artefacts, children).items()):
        a = by_id[aid]
        action, code, why = decide_artefact(a, subject, via, request, holds, operator_role)
        plans.append(Plan(request_id=request["request_id"], subject_id=subject, artefact_id=aid,
                          artefact_type=a.get("type", ""), found_via=via, action=action, reason_code=code, reason=why,
                          legal_hold=str(a.get("legal_hold") or holds.get(aid, ("", ""))[0] or ""),
                          deadline=str(request.get("deadline", ""))))
    return plans


def plan_all(requests: list[dict], artefacts: list[dict], hold_scope: str = "copies",
             operator_role: str = "data-platform") -> list[Plan]:
    ids = [a["artefact_id"] for a in artefacts]
    if len(ids) != len(set(ids)):
        raise ValueError("data_graph has duplicate artefact_id values")
    rids = [r["request_id"] for r in requests]
    if len(rids) != len(set(rids)):
        raise ValueError("requests has duplicate request_id values")
    known = set(ids)
    dangling = sorted({p for a in artefacts for p in (a.get("parent_ids") or []) if p not in known})
    if dangling:
        raise ValueError(f"data_graph has parent_ids pointing to unknown artefacts: {dangling[:5]}")
    children = children_index(artefacts)
    holds = held_ids(artefacts, children, hold_scope)
    out: list[Plan] = []
    for r in sorted(requests, key=lambda r: r["request_id"]):
        out.extend(plan_request(r, artefacts, children, holds, operator_role))
    return out

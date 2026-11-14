Baseline: `baseline` (git ba43778, seed 42) · PoC: `poc` (git ba43778, seed 42)

| Metric (unit) | Slice | Baseline | PoC | Δ abs | Δ rel | Better | N |
|---|---|---|---|---|---|---|---|
| **Deletion Completeness** (must-delete artefacts deleted / must-delete artefacts) | all | 0.0556 | 1.0000 | 0.9444 | +1700.0% | higher | 48 |
| False-delete count (count (target 0): exceptions deleted + deletes outside request scope) | all | 1.0000 | 0.0000 | -1.0000 | -100.0% | lower | None |
| Exception handling accuracy (legal-hold/escalate rows handled as expected / such rows) | all | 0.0000 | 1.0000 | 1.0000 | baseline=0 | higher | None |
| Audit trace completeness (actions with an audit entry / actions) | all | 1.0000 | 1.0000 | 0.0000 | +0.0% | higher | None |
| Runtime / 100 items (s) | all | 0.4340 | 0.6526 | | | lower | |

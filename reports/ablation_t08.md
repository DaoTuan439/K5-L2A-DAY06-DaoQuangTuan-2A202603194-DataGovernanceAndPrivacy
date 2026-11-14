# T08 ablation (dev gold, official evaluator)

Gold: `reports\gold\t08_dev_gold.csv` (N=48, DR-002 + DR-004). Frozen config: `hold_scope=copies`, all rules on. Numbers are a self-check, **not** the official hidden-eval score.

## 1 · hold_scope sensitivity

Rows = how the instructor GT might define legal-hold scope; `PoC hold_scope` = our setting.

| GT reading of legal hold | PoC hold_scope | Deletion Completeness | False-delete count | Exception acc. | fixture: delete / retain / escalate |
|---|---|---|---|---|---|
| self | self | 1.0 | 0 | 1.0 | 128/2/28 |
| self | copies | 0.973 | 0 | 1.0 | 126/4/28 |
| self | descendants | 0.649 | 0 | 0.636 | 102/40/16 |
| copies | self | 1.0 | 1 | 0.917 | 128/2/28 |
| copies | copies | 1.0 | 0 | 1.0 | 126/4/28 |
| copies | descendants | 0.667 | 0 | 0.667 | 102/40/16 |
| descendants | self | 1.0 | 13 | 0.458 | 128/2/28 |
| descendants | copies | 1.0 | 12 | 0.5 | 126/4/28 |
| descendants | descendants | 1.0 | 0 | 0.833 | 102/40/16 |

Worst case per setting (max false-delete, min completeness over the 3 GT readings):

| PoC hold_scope | worst_false_delete | worst_completeness |
|---|---|---|
| copies | 12 | 0.973 |
| descendants | 0 | 0.649 |
| self | 13 | 1.0 |

## 2 · Drop-one-rule ablation (GT reading = copies)

| variant | Deletion Completeness | False-delete count | Exception acc. | fixture: delete / retain / escalate |
|---|---|---|---|---|
| full policy (frozen) | 1.0 | 0 | 1.0 | 126/4/28 |
| - legal_hold | 1.0 | 2 | 0.833 | 130/0/28 |
| - identity | 1.0 | 0 | 1.0 | 126/4/28 |
| - acl | 1.0 | 1 | 0.917 | 127/4/27 |
| - origin | 1.0 | 3 | 0.75 | 129/4/25 |
| - multi_subject | 1.0 | 6 | 0.5 | 150/4/4 |
| - lineage | 1.0 | 0 | 1.0 | 126/4/28 |
| - all exception rules | 1.0 | 12 | 0.0 | 158/0/0 |

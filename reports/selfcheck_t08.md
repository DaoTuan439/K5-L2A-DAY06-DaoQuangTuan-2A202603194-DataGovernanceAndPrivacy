# T08 self-check vs dev gold (`reports\gold\t08_dev_gold.csv`)

Gold: 33 (request, artefact) rows, requests ['DR-002', 'DR-004'], labeller ['daoquangtuan']. Official evaluator `eval_t08`, Wilson 95% CI. **Not** the official score.

## out/baseline/actions.csv

| metric | value | k | n | wilson95_lo | wilson95_hi |
|---|---|---|---|---|---|
| Deletion Completeness | 0.043478260869565216 | 1.0 | 23.0 | 0.008 | 0.21 |
| False-delete count | 1.0 |  |  |  |  |
| Exception handling accuracy | 0.0 | 0.0 | 10.0 | 0.0 | 0.278 |

Per artefact type:

| type | correct | n |
|---|---|---|
| annotation | 0 | 7 |
| backup | 0 | 2 |
| embedding | 0 | 6 |
| face_crop | 0 | 6 |
| frame | 0 | 7 |
| raw_video | 1 | 2 |
| training_export | 0 | 3 |

Disagreements with gold:

| request_id | artefact_id | type | gold_group | gold_action | action | confidence |
|---|---|---|---|---|---|---|
| DR-002 | a0043 | raw_video | A | retain_legal_hold | delete | high |
| DR-002 | a0044 | backup | B | retain_legal_hold | (missing) | medium |
| DR-002 | a0045 | frame | C | delete | (missing) | medium |
| DR-002 | a0046 | face_crop | C | delete | (missing) | medium |
| DR-002 | a0047 | embedding | C | delete | (missing) | medium |
| DR-002 | a0048 | annotation | C | delete | (missing) | medium |
| DR-002 | a0049 | frame | C | delete | (missing) | medium |
| DR-002 | a0050 | face_crop | C | delete | (missing) | medium |
| DR-002 | a0051 | embedding | C | delete | (missing) | medium |
| DR-002 | a0052 | annotation | C | delete | (missing) | medium |
| DR-002 | a0053 | frame | C | delete | (missing) | medium |
| DR-002 | a0054 | face_crop | C | delete | (missing) | medium |
| DR-002 | a0055 | embedding | C | delete | (missing) | medium |
| DR-002 | a0056 | annotation | C | delete | (missing) | medium |
| DR-002 | a0211 | training_export | D | escalate | (missing) | high |
| DR-004 | a0067 | frame | E | escalate | (missing) | high |
| DR-004 | a0070 | annotation | E | escalate | (missing) | high |
| DR-004 | a0072 | backup | G | delete | (missing) | high |
| DR-004 | a0073 | frame | G | delete | (missing) | high |
| DR-004 | a0074 | face_crop | G | delete | (missing) | high |
| DR-004 | a0075 | embedding | F | escalate | (missing) | high |
| DR-004 | a0076 | annotation | G | delete | (missing) | high |
| DR-004 | a0077 | frame | G | delete | (missing) | high |
| DR-004 | a0078 | face_crop | G | delete | (missing) | high |
| DR-004 | a0079 | embedding | F | escalate | (missing) | high |
| DR-004 | a0080 | annotation | G | delete | (missing) | high |
| DR-004 | a0081 | frame | G | delete | (missing) | high |
| DR-004 | a0082 | face_crop | G | delete | (missing) | high |
| DR-004 | a0083 | embedding | F | escalate | (missing) | high |
| DR-004 | a0084 | annotation | G | delete | (missing) | high |
| DR-004 | a0211 | training_export | D | escalate | (missing) | high |
| DR-004 | a0212 | training_export | D | escalate | (missing) | high |

## out/poc/actions.csv

| metric | value | k | n | wilson95_lo | wilson95_hi |
|---|---|---|---|---|---|
| Deletion Completeness | 1.0 | 23.0 | 23.0 | 0.857 | 1.0 |
| False-delete count | 0.0 |  |  |  |  |
| Exception handling accuracy | 1.0 | 10.0 | 10.0 | 0.722 | 1.0 |

Per artefact type:

| type | correct | n |
|---|---|---|
| annotation | 7 | 7 |
| backup | 2 | 2 |
| embedding | 6 | 6 |
| face_crop | 6 | 6 |
| frame | 7 | 7 |
| raw_video | 2 | 2 |
| training_export | 3 | 3 |

No disagreement with gold.

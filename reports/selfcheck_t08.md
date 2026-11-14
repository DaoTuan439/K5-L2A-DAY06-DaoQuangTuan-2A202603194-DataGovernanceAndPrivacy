# T08 self-check vs dev gold (`reports\gold\t08_dev_gold.csv`)

Gold: 48 (request, artefact) rows, requests ['DR-002', 'DR-004', 'DR-008'], labeller ['daoquangtuan']. Official evaluator `eval_t08`, Wilson 95% CI. **Not** the official score.

## out/baseline/actions.csv

| metric | value | k | n | wilson95_lo | wilson95_hi |
|---|---|---|---|---|---|
| Deletion Completeness | 0.05555555555555555 | 2.0 | 36.0 | 0.015 | 0.181 |
| False-delete count | 1.0 |  |  |  |  |
| Exception handling accuracy | 0.0 | 0.0 | 12.0 | 0.0 | 0.242 |

Per artefact type:

| type | correct | n |
|---|---|---|
| annotation | 0 | 10 |
| backup | 0 | 3 |
| embedding | 0 | 9 |
| face_crop | 0 | 9 |
| frame | 0 | 10 |
| raw_video | 2 | 3 |
| training_export | 0 | 4 |

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
| DR-008 | a0156 | backup | H | escalate | (missing) | high |
| DR-008 | a0157 | frame | G | delete | (missing) | high |
| DR-008 | a0158 | face_crop | G | delete | (missing) | high |
| DR-008 | a0159 | embedding | G | delete | (missing) | high |
| DR-008 | a0160 | annotation | G | delete | (missing) | high |
| DR-008 | a0161 | frame | G | delete | (missing) | high |
| DR-008 | a0162 | face_crop | G | delete | (missing) | high |
| DR-008 | a0163 | embedding | G | delete | (missing) | high |
| DR-008 | a0164 | annotation | G | delete | (missing) | high |
| DR-008 | a0165 | frame | G | delete | (missing) | high |
| DR-008 | a0166 | face_crop | G | delete | (missing) | high |
| DR-008 | a0167 | embedding | G | delete | (missing) | high |
| DR-008 | a0168 | annotation | G | delete | (missing) | high |
| DR-008 | a0211 | training_export | D | escalate | (missing) | high |

## out/poc/actions.csv

| metric | value | k | n | wilson95_lo | wilson95_hi |
|---|---|---|---|---|---|
| Deletion Completeness | 1.0 | 36.0 | 36.0 | 0.904 | 1.0 |
| False-delete count | 0.0 |  |  |  |  |
| Exception handling accuracy | 1.0 | 12.0 | 12.0 | 0.758 | 1.0 |

Per artefact type:

| type | correct | n |
|---|---|---|
| annotation | 10 | 10 |
| backup | 3 | 3 |
| embedding | 9 | 9 |
| face_crop | 9 | 9 |
| frame | 10 | 10 |
| raw_video | 3 | 3 |
| training_export | 4 | 4 |

No disagreement with gold.

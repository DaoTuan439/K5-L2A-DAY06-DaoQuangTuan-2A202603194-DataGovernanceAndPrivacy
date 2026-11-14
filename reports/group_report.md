# Group Report — Day 06 Data Lab (Field-to-Release PoC)

> Mọi con số dưới đây lấy từ file do script sinh ra: `reports/selfcheck_t08.md`, `reports/ablation_t08.md`,
> `out/*/run_info.json`, `out/poc/decision.json`. **Điểm chính thức** (`reports/metrics_*.json`,
> `reports/table1_baseline_vs_poc.md`) chỉ sinh được khi giảng viên cài overlay `gt/`; repo học viên chạy
> `python -m src.evaluate --track t08 ...` → exit 2 "ground truth file not found" (đã kiểm). Vì vậy bảng 1 dùng
> **dev gold tự gán nhãn** (N=33), cùng evaluator chính thức `eval_t08`.

## 00 · Header

| Mục | Giá trị |
|---|---|
| Group ID | G08 |
| Challenge | T08 · Retention & Delete Request Simulator |
| Thành viên + vai trò | 1. daoquangtuan (nhóm 1 người): Lead/Integrator · Data & GT · Core algorithm · QA/metric · Review + report |
| Git URL | https://github.com/DaoTuan439/K5-L2A-DAY06-DaoQuangTuan-2A202603194-DataGovernanceAndPrivacy |
| Tag `demo-180m` (commit) | `demo-180m` → commit gắn tag cùng report này (xem `git show demo-180m`) |
| Tag `final-24h` (commit) | `final-24h` → commit gắn tag cùng bản report này (xem `git show final-24h`) |
| Deadline (giờ VN) | 12:00 15/11/2026 |

## 01 · Problem statement

- **Ai bị ảnh hưởng?** Chủ thể dữ liệu (tài xế/người đi đường trong video) gửi yêu cầu xóa. Nếu hệ thống *bỏ sót* backup/embedding thì dữ liệu định danh vẫn còn, vi phạm quyền xóa. Nếu hệ thống *xóa nhầm* dữ liệu đang legal hold hoặc dữ liệu của người khác thì công ty mất bằng chứng pháp lý và gây hại cho bên thứ ba.
- **Điểm nghẽn:** dữ liệu của một người bị nhân bản qua pipeline: raw → frame → face_crop → embedding, annotation, backup, training_export. Xóa theo filename chỉ chạm tới raw.
- **Đầu vào → đầu ra:** `requests.json` (10 yêu cầu) + `data_graph.json` (212 artefact, mock-graph-1) → `actions.csv` (158 cặp request×artefact, action ∈ {delete, retain_legal_hold, escalate}) + `audit_log.jsonl` + bằng chứng xóa mock + decision.
- **Tiêu chí GO / HOLD** (chốt trước eval, `src/pipeline.py::decide`): **HOLD** `EXCEPTIONS_PENDING_REVIEW` khi còn ≥1 artefact `escalate` chưa được người duyệt approve. **GO** `REQUESTS_RESOLVED` khi mọi exception đã có quyết định người duyệt. Không có trạng thái tự release khi còn exception.
- **Giả định cần DPO/legal xác nhận:** (1) legal hold áp cho artefact bị hold **và bản sao chính xác** (backup), không áp cho dữ liệu dẫn xuất; (2) artefact nhiều subject phải redact/re-export, không xóa nguyên file; (3) operator `data-platform` không được xóa artefact có ACL của vendor khác.

## 02 · Data & provenance

| Split | N | Nguồn / link | License | Synthetic? |
|---|---|---|---|---|
| dev (fixture) | 10 request × 212 artefact → 158 cặp trong phạm vi | `fixtures/t08_deletion/` (synthetic: tools/make_fixtures.py seed 42) | CC0-1.0 | Có, mock, không xóa dữ liệu thật |
| dev gold (tự gán nhãn) | 33 cặp (DR-002, DR-004) | `reports/gold/t08_dev_gold.csv` + protocol `reports/gold/README.md` | CC0-1.0 | Có |
| eval / heldout | ẩn | hidden eval của giảng viên (seed bí mật), cùng cấu trúc | — | Có |

- **Schema:** artefact `{artefact_id, type, subject_ids, parent_ids, uri, owner, acl, legal_hold, origin_known, created_at, filename?}`; request `{request_id, subject_id, received_at, deadline, channel, identity_verified}`.
- **Fixture có:** 2 raw legal hold (a0043 LH-2026-03, a0099 LH-2026-07), 1 backup ACL `vendor-x` (a0156), 3 embedding `origin_known=False` (a0075/79/83), 8 frame/annotation 2 subject, 2 training_export 9–10 subject.
- Seed 42 (pipeline tất định, không dùng random). Không chia split: đơn vị là request; eval chính thức nằm ở hidden eval.
- `manifest.csv` verified: **có**. `python -m tools.verify_manifests` → "14 manifests, 0 failing". *Lưu ý Windows:* Git `core.autocrlf=true` làm lệch sha256 của mọi file text; repo đặt `git config core.autocrlf false`.
- Dữ liệu thật: không dùng (đề cấm xóa dữ liệu thực).

## 03 · Research & design

- **Kỹ thuật:** duyệt đồ thị lineage (BFS parent → child) + policy precedence, theo gợi ý `docs/tracks/T08.md` §8. Chọn luật tất định thay vì model vì (a) yêu cầu xóa cần giải thích được từng quyết định cho DPO, (b) không có dữ liệu huấn luyện, (c) tổng quát sang hidden eval với seed khác.
- **Data flow:**
  ```
  requests.json + data_graph.json ──01 load (sha256 manifest)──▶ 02 process
    scope = artefact gắn subject ∪ hậu duệ (BFS) của artefact chỉ thuộc subject
    policy: legal_hold → identity → ACL → origin → multi-subject → lineage-only → delete
  ──▶ 03 rank: mọi exception vào review_queue.csv (+ contact_sheet.html), ưu tiên theo reason
  ──▶ 04 review: review_queue_reviewed.csv → override có guard (hold không thể → delete) → audit_log.jsonl
  ──▶ 05 decide: dry-run plan → mock delete idempotent (mock_store.json, tombstone) → GO/HOLD + reason_code + owner
  ```
- **Offline:** không model, không weights, không network (`--offline` guard bật).
- **Trade-offs:**
  - *Phạm vi hold:* `copies` (chốt), so với `self` (rủi ro xóa backup bằng chứng) và `descendants` (an toàn nhưng completeness 0.46). Xem §06 ablation.
  - *Artefact chỉ tìm thấy qua lineage* (không có tag subject) → escalate, không tự xóa. Đổi lại một ít completeness để đảm bảo không xóa ngoài phạm vi.
  - *Nhiều subject* → escalate. Dữ liệu người yêu cầu còn nằm trong frame cho tới khi redact, đổi lại không xóa dữ liệu người khác.

## 04 · Baseline vs PoC

- **Baseline** (`src/baseline_t08.py`, commit 3aba54b): với mỗi request, `delete` mọi `raw_video` có filename chứa `_<subject_id>_`. Không lineage, không exception (đúng mô tả T08.md §4).
- **PoC** (`src/pipeline.py` + `src/t08_lineage.py`, config `configs/lab.yaml`: `hold_scope=copies`, `operator_role=data-platform`, `dry_run=false`).
- Cùng input, cùng seed 42, cùng evaluator, cùng gold: **xác nhận**.

**Bảng 1 · Baseline vs PoC** — `python -m tools.t08_selfcheck --pred out/baseline/actions.csv out/poc/actions.csv` (dev gold N=33, Wilson 95% CI):

| Metric (unit) | Baseline | PoC | Δ & chú thích |
|---|---|---|---|
| **Primary: Deletion Completeness** (higher) | 1/23 = 0.043 [0.008, 0.210] | 23/23 = 1.000 [0.857, 1.000] | +0.957. Baseline chỉ xóa đúng 1 raw. |
| False-delete count (lower, mục tiêu 0) | **1** (xóa raw a0043 đang legal hold) | **0** | −1 |
| Hard-slice: Exception handling accuracy | 0/10 = 0.000 [0.000, 0.278] | 10/10 = 1.000 [0.722, 1.000] | N=10 dòng hold/escalate |
| Review queue | 0 dòng (không review) | 32 dòng exception, 32/32 đã duyệt | B = toàn bộ exception |
| Runtime (CPU, `run_info.json`) | 0.0335 s cho 10 dòng | 0.5008 s cho 158 dòng ≈ 0.32 s / 100 dòng | Intel64 Fam 6 Model 165, Win 11, Python 3.13.5 |

> PoC = 1.000 trên dev gold **không** phải bằng chứng mạnh: gold và policy cùng suy ra từ một spec (xem §09). Rủi ro thật ở phạm vi legal hold, đo trong §06.

## 05 · Evaluation protocol

- **Primary:** Deletion Completeness = số cặp GT `delete` mà ta `delete` / số cặp GT `delete`. Đơn vị là cặp (request_id, artefact_id), khớp chính xác theo khóa; cặp thiếu trong `actions.csv` = không xóa. **Phụ:** False-delete count (exception bị xóa + xóa ngoài phạm vi GT), Exception handling accuracy, Audit trace completeness. Chi tiết: `reports/metric_contract.md`.
- **Threshold / budget:** không có ngưỡng số. Policy và tham số chốt ngày 2026-11-14 trong `configs/lab.yaml` **trước** khi chạy self-check; ablation chỉ để báo cáo, không tune lại.
- **Độ bất định:** Wilson 95% CI (`src/metrics/estimation.wilson_ci`) cho mọi tỉ lệ; báo kèm k/N.
- **Lệnh:** chính thức (giảng viên): `python -m src.evaluate --track t08 --pred out/poc/actions.csv --out reports/metrics_poc.json`; tự kiểm: `python -m tools.t08_selfcheck --pred out/baseline/actions.csv out/poc/actions.csv --out reports/selfcheck_t08.md`.

## 06 · Result slices

**Theo loại artefact** (dev gold, số đúng / N, `reports/selfcheck_t08.md`):

| Slice | N | Baseline | PoC | Ghi chú |
|---|---|---|---|---|
| raw_video | 2 | 1/2 | 2/2 | baseline xóa raw đang hold |
| backup | 2 | 0/2 | 2/2 | baseline không tìm backup |
| embedding (định danh) | 6 | 0/6 | 6/6 | gồm 3 origin unknown → escalate |
| frame + face_crop + annotation | 20 | 0/20 | 20/20 | gồm 2 dòng nhiều subject |
| training_export | 3 | 0/3 | 3/3 | nhiều subject → escalate |

**Ablation 1 · hold_scope × cách hiểu legal hold của GT** (`python -m tools.t08_ablation`):

| PoC hold_scope | GT = self | GT = copies | GT = descendants | Worst false-delete |
|---|---|---|---|---|
| self | compl 1.000 · FD 0 | compl 1.000 · FD 1 | compl 1.000 · FD 13 | 13 |
| **copies (chốt)** | compl 0.958 · FD 0 | compl 1.000 · FD 0 | compl 1.000 · FD 12 | 12 |
| descendants | compl 0.458 · FD 0 | compl 0.478 · FD 0 | compl 1.000 · FD 0 | 0 |

**Ablation 2 · bỏ từng luật** (GT = copies): bỏ `multi_subject` → FD 5, exception acc 0.5; bỏ `origin` → FD 3; bỏ `legal_hold` → FD 2; bỏ tất cả → FD 10, exception acc 0.0. Bỏ `identity` / `acl` / `lineage` **không đổi gì trên dev gold**: fixture không có request chưa xác minh, backup vendor-x (DR-008) không nằm trong gold, không có artefact mất tag. Ba luật này chỉ được kiểm bằng unit test (`tests/test_t08.py`).

- **Failure case 1 (baseline, failure mode bắt buộc "xóa nhầm exception; chỉ xóa raw nhưng giữ bản sao và embedding định danh"):** DR-002 / subj_03. Baseline `delete` a0043 (`raw_video`, `legal_hold: LH-2026-03`), làm mất bằng chứng đang bị giữ. Đồng thời baseline bỏ qua backup a0044 và 3 embedding định danh a0047/a0051/a0055, nên dữ liệu khuôn mặt của subj_03 vẫn tồn tại sau khi "xóa xong". **Root cause:** xóa theo filename, không duyệt lineage, không kiểm `legal_hold` trước khi xóa.
- **Failure case 2 (PoC, rủi ro còn lại):** phạm vi legal hold không được spec định nghĩa rõ. Với DR-002, PoC giữ a0043 + backup a0044 nhưng **xóa** 12 frame/crop/embedding/annotation dẫn xuất từ raw đang hold. Nếu legal hold LH-2026-03 thực chất bao cả dữ liệu dẫn xuất thì PoC có **12 false-delete** (ablation 1, hàng copies / GT descendants). **Root cause:** policy ngầm định "bằng chứng = bản gốc + bản sao". **Cách giảm:** hold record nên khai báo scope (`self | copies | descendants`) để pipeline đọc thay vì đoán; trước khi có điều đó, hold scope là câu hỏi bắt buộc cho legal.
- **Failure case 3 (PoC, giới hạn nghiệp vụ):** 24 dòng nhiều subject (vd frame a0011 chứa subj_00 + subj_01 trong DR-001) được escalate. Vì vậy dữ liệu của người yêu cầu **vẫn còn** cho tới khi redact/re-export xong. Metric tính đúng (escalate), nhưng quyền xóa chỉ được thực hiện trọn khi ticket redact đóng trước deadline (2026-12-01 với DR-001).
- **Latency:** 0.50 s / 158 dòng trên CPU laptop (Intel64 Fam 6 Model 165, Windows 11, Python 3.13.5).

## 07 · Human & decision

- **Review queue:** `out/poc/review_queue.csv` + `out/poc/contact_sheet.html` (offline, nút Export CSV). B = mọi exception (32), ưu tiên LEGAL_HOLD (1.0) > LEGAL_HOLD_INHERITED > IDENTITY > NO_PERMISSION > ORIGIN_UNKNOWN > MULTI_SUBJECT > lineage-only.
- **Quyết định người duyệt:** `reports/review_queue_reviewed.csv`. Reviewer daoquangtuan, 2026-11-14, 32/32 `approve`, mỗi dòng có `review_note`: giữ hold và hẹn xóa khi hết hold; redact/re-export artefact nhiều subject; data owner xác minh lineage embedding; chuyển vendor-x xóa backup a0156 và gửi bằng chứng. Pipeline đọc file qua `params.review_file`, nên clean clone vẫn tái lập.
- **Override + audit:** `edit`/`reject` + `override_value ∈ {delete, retain_legal_hold, escalate}`; **guard:** artefact legal hold không thể override thành `delete` (ghi `override_blocked`, test `test_reviewer_cannot_override_legal_hold_to_delete`). `out/poc/audit_log.jsonl` (append-only) có: 126 `plan:delete`, 28 `plan:escalate`, 4 `plan:retain_legal_hold`, 32 `review:approve`, 126 `mock_delete`, nghĩa là mọi action đều có audit entry.
- **Decision:** trước review là `HOLD` / `EXCEPTIONS_PENDING_REVIEW` (28 escalation chưa giải quyết). Sau review là `GO` / `REQUESTS_RESOLVED`, owner "daoquangtuan (Data Protection Lead)", metrics {delete 126, retain 4, escalate 28, unresolved 0} (`out/poc/decision.json`, `reports/decision_log.csv`).
- **Khi nào HOLD:** còn escalation chưa duyệt; reviewer chọn `escalate`/`skip`; request chưa xác minh danh tính. GO không có nghĩa là xóa artefact đang hold: chúng được giữ và hẹn xóa khi hold được giải phóng.

## 08 · Reproduce & tests

```bash
# Windows: không có make → dùng lệnh python trực tiếp; giữ LF để khớp sha256
git config core.autocrlf false
pip install -r requirements.txt
python -m src.main --track t08 --pipeline src.baseline_t08 --output out/baseline --run-name baseline --offline --seed 42
python -m src.main --config configs/lab.yaml --track t08 --output out/poc --run-name poc --offline --seed 42
python -m tools.t08_selfcheck --pred out/baseline/actions.csv out/poc/actions.csv --out reports/selfcheck_t08.md
python -m tools.t08_ablation --out reports/ablation_t08.md
python -m pytest -q
# chính thức (cần overlay gt/ của giảng viên):
python -m src.evaluate --track t08 --pred out/poc/actions.csv --run-name poc --out reports/metrics_poc.json
```

- `pytest`: **57 passed, 39 skipped** (skip = test cần GT giảng viên); riêng `tests/test_t08.py`: **10 passed**: E2E + idempotency (chạy 2 lần cùng `actions.csv`, lần 2 toàn `already_deleted`), PoC > baseline, legal hold + backup, guard override, identity/ACL/origin/multi-subject, artefact mất tag, graph hỏng (trùng id, parent treo), review file cũ (exit 2), toggle ablation.
- Lệnh contract `python -m src.main --input fixtures/t08_deletion --config configs/lab.yaml --output out/contract --offline --seed 42` → exit 0.
- Máy: Windows 11 (10.0.26300), Intel64 Family 6 Model 165, Python 3.13.5 · git sha: xem tag `demo-180m`.

## 09 · Limitations & ethics

- **Dev gold không độc lập với policy:** nhãn được soạn từ cùng spec `T08.md` (có hỗ trợ của trợ lý AI, labeller daoquangtuan duyệt), 1 labeller, N=33. Kết quả 1.000 chỉ chứng minh code cài đúng cách hiểu spec. Điểm thật phụ thuộc hidden eval.
- **Rủi ro pháp lý:** phạm vi legal hold (§06 failure 2) và cách xử lý artefact nhiều subject cần DPO/legal xác nhận. Đây là tình huống học tập, **không** tuyên bố "đạt GDPR Art.17 / Luật 91/2025 / NĐ 356/2025".
- **Chưa làm:** SLA dashboard / nhắc deadline; resume khi job bị ngắt (mới có idempotency qua tombstone); notification cho vendor-x; lịch xóa tự động khi hold hết hạn; xóa thật trên storage (mock).
- **Scale 10×** (~2 000 artefact, 100 request): BFS O(V+E) mỗi request, vẫn dưới giây. Hàng chờ review tăng tuyến tính (~320 dòng), nên cần gom theo artefact (training_export a0211 xuất hiện trong 8 request nên duyệt 1 lần).
- **False alarm:** escalate thừa làm chậm việc đóng request nhưng không gây xóa nhầm. Nhóm chấp nhận trade-off này.

## 10 · Team contribution

**Bảng 2** (đối chiếu `git shortlog -sne --all`: `Dao Tuan <tuan.dao3@sotatek.com>`; các commit của loversky02 / Tin Duong là starter repo của giảng viên):

| Học viên | Git author/email | Module / vai trò | Commit SHA / diff chứng minh | Trình bày? |
|---|---|---|---|---|
| daoquangtuan | Dao Tuan <tuan.dao3@sotatek.com> | Toàn bộ (nhóm 1 người): core algorithm, baseline, pipeline/HITL, tests, gold + metric, ablation, report | e2fbe6d, 3aba54b, 12f26a5, 9b27bc5, 86c5330, 9cffbe8, 10de1f1, 6143f99 + commit report | Có |

## 11 · References

| URL | Ngày xem | 1–2 dòng ý nghĩa |
|---|---|---|
| `docs/tracks/T08.md` (repo lab) | 2026-11-14 | Định nghĩa bài toán, baseline, failure mode bắt buộc, gợi ý policy precedence legal hold > permission > multi-subject > delete |
| https://eur-lex.europa.eu/eli/reg/2016/679/oj (GDPR, Art.17) | ____ | Quyền xóa và ngoại lệ Art.17(3), cơ sở cho nhãn retain khi có nghĩa vụ pháp lý / legal claims |
| https://thuvienphapluat.vn/van-ban/Bo-may-hanh-chinh/Luat-Bao-ve-du-lieu-ca-nhan-2025-so-91-2025-QH15-625628.aspx (Luật 91/2025/QH15) | ____ | Quyền xóa dữ liệu cá nhân và các trường hợp ngoại lệ ở VN |
| Nghị định 356/2025 (Research Shelf trong handout) | ____ | Hướng dẫn thi hành luật BVDLCN |

---

**Bảng 3 · Checklist chốt khi nộp**

- [x] Link repo và tag cuối `final-24h` trong report; input mẫu không chứa PII thật (fixture synthetic CC0). Slide demo: `demo/G08_T08_demo_slides.pdf`.
- [x] Đúng 1 lệnh run, 1 lệnh evaluate, 1 lệnh tests; không cần download khi chạy.
- [x] Có baseline/PoC metrics (dev gold), 3 failure case, reviewer evidence, decision log.
- [x] Có license/source provenance, seed, offline environment, GT/eval N.
- [x] Thành viên duy nhất có commit thực chất và được nêu trong bảng trên.

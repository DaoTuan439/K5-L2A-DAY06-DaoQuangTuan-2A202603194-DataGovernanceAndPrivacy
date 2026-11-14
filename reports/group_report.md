# Group Report — Day 06 Data Lab (Field-to-Release PoC)

> Mọi con số dưới đây lấy từ file do script sinh ra: `reports/selfcheck_t08.md`, `reports/ablation_t08.md`,
> `out/*/run_info.json`, `out/poc/decision.json`. Repo học viên không có `gt/`: `python -m src.evaluate --track t08 ...`
> không có `--gt` thì exit 2 "ground truth file not found" (đã kiểm). Vì vậy `reports/metrics_baseline.json`,
> `reports/metrics_poc.json`, `reports/table1_baseline_vs_poc.md` hiện được sinh bằng **đúng các lệnh của đề** với
> `--gt reports/gold/t08_dev_gt_actions.csv` (**dev gold tự gán nhãn**, N=48; trường `extra.gt` trong JSON ghi rõ),
> pred giới hạn ở DR-002/DR-004/DR-008. **Không phải điểm chính thức.** Giảng viên chạy lại với GT thật sẽ ghi đè 3 file này.

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
| dev gold (tự gán nhãn) | 48 cặp (DR-002, DR-004, DR-008) | `reports/gold/t08_dev_gold.csv` + protocol `reports/gold/README.md` | CC0-1.0 | Có |
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

**Bảng 1 · Baseline vs PoC** — `python -m tools.t08_selfcheck --pred out/baseline/actions.csv out/poc/actions.csv` (dev gold N=48, Wilson 95% CI):

| Metric (unit) | Baseline | PoC | Δ & chú thích |
|---|---|---|---|
| **Primary: Deletion Completeness** (higher) | 2/36 = 0.056 [0.015, 0.181] | 36/36 = 1.000 [0.904, 1.000] | +0.944. Baseline chỉ xóa đúng 2 raw. |
| False-delete count (lower, mục tiêu 0) | **1** (xóa raw a0043 đang legal hold) | **0** | −1 |
| Hard-slice: Exception handling accuracy | 0/12 = 0.000 [0.000, 0.242] | 12/12 = 1.000 [0.758, 1.000] | N=12 dòng hold/escalate |
| Review queue | 0 dòng (không review) | 32 dòng exception, 32/32 đã duyệt | B = toàn bộ exception |
| Runtime (CPU, `run_info.json`) | 0.0335 s cho 10 dòng | 1.0042 s cho 158 dòng ≈ 0.64 s / 100 dòng (gồm checkpoint sau mỗi lần xóa) | Intel64 Fam 6 Model 165, Win 11, Python 3.13.5 |

Cùng chuỗi lệnh chính thức (`src.evaluate` + `src.compare`), chỉ thay `--gt` bằng dev gold, sinh ra `reports/metrics_baseline_devgold.json`, `reports/metrics_poc_devgold.json` và `reports/table1_baseline_vs_poc_devgold.md` (JSON ghi rõ `gt=reports/gold/t08_dev_gt_actions.csv`). Audit trace completeness: baseline 3/3, PoC 48/48. Hậu tố `_devgold` để không lẫn với file chính thức giảng viên sinh.

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
| raw_video | 3 | 2/3 | 3/3 | baseline xóa raw đang hold (a0043) |
| backup | 3 | 0/3 | 3/3 | baseline không tìm backup; gồm a0156 ACL vendor-x → escalate |
| embedding (định danh) | 9 | 0/9 | 9/9 | gồm 3 origin unknown → escalate |
| frame + face_crop + annotation | 29 | 0/29 | 29/29 | gồm 2 dòng nhiều subject |
| training_export | 4 | 0/4 | 4/4 | nhiều subject → escalate |

**Ablation 1 · hold_scope × cách hiểu legal hold của GT** (`python -m tools.t08_ablation`):

| PoC hold_scope | GT = self | GT = copies | GT = descendants | Worst false-delete |
|---|---|---|---|---|
| self | compl 1.000 · FD 0 | compl 1.000 · FD 1 | compl 1.000 · FD 13 | 13 |
| **copies (chốt)** | compl 0.973 · FD 0 | compl 1.000 · FD 0 | compl 1.000 · FD 12 | 12 |
| descendants | compl 0.649 · FD 0 | compl 0.667 · FD 0 | compl 1.000 · FD 0 | 0 |

**Ablation 2 · bỏ từng luật** (GT = copies): bỏ `multi_subject` → FD 6, exception acc 0.5; bỏ `origin` → FD 3; bỏ `legal_hold` → FD 2; bỏ `acl` → FD 1 (xóa backup a0156 của vendor-x); bỏ tất cả → FD 12, exception acc 0.0. Bỏ `identity` / `lineage` **không đổi gì trên dev gold**: fixture không có request chưa xác minh, không có artefact mất tag. Hai luật này chỉ được kiểm bằng unit test (`tests/test_t08.py`).

- **Failure case 1 (baseline, failure mode bắt buộc "xóa nhầm exception; chỉ xóa raw nhưng giữ bản sao và embedding định danh"):** DR-002 / subj_03. Baseline `delete` a0043 (`raw_video`, `legal_hold: LH-2026-03`), làm mất bằng chứng đang bị giữ. Đồng thời baseline bỏ qua backup a0044 và 3 embedding định danh a0047/a0051/a0055, nên dữ liệu khuôn mặt của subj_03 vẫn tồn tại sau khi "xóa xong". **Root cause:** xóa theo filename, không duyệt lineage, không kiểm `legal_hold` trước khi xóa.
- **Failure case 2 (PoC, rủi ro còn lại):** phạm vi legal hold không được spec định nghĩa rõ. Với DR-002, PoC giữ a0043 + backup a0044 nhưng **xóa** 12 frame/crop/embedding/annotation dẫn xuất từ raw đang hold. Nếu legal hold LH-2026-03 thực chất bao cả dữ liệu dẫn xuất thì PoC có **12 false-delete** (ablation 1, hàng copies / GT descendants). **Root cause:** policy ngầm định "bằng chứng = bản gốc + bản sao". **Cách giảm:** hold record nên khai báo scope (`self | copies | descendants`) để pipeline đọc thay vì đoán; trước khi có điều đó, hold scope là câu hỏi bắt buộc cho legal.
- **Failure case 3 (PoC, giới hạn nghiệp vụ):** 24 dòng nhiều subject (vd frame a0011 chứa subj_00 + subj_01 trong DR-001) được escalate. Vì vậy dữ liệu của người yêu cầu **vẫn còn** cho tới khi redact/re-export xong. Metric tính đúng (escalate), nhưng quyền xóa chỉ được thực hiện trọn khi ticket redact đóng trước deadline (2026-12-01 với DR-001).
- **Failure case 4 (lỗi thật gặp khi chạy, đã sửa):** trên Windows, `os.replace` khi checkpoint `mock_store.json` bị `PermissionError` (file trong `out/poc` bị antivirus / IDE file watcher khóa tạm thời), nên job xóa dừng giữa chừng. Vì store được checkpoint sau mỗi lần xóa, trạng thái không hỏng: lần chạy lại hoàn tất, `deletion_evidence.csv` = 16 `already_deleted` + 110 `deleted`, mỗi artefact xóa đúng 1 lần. **Root cause:** ghi đè file trên Windows không atomic khi có tiến trình khác giữ handle. **Sửa:** retry có backoff khi `replace`; test `test_interrupted_mock_delete_resumes_without_double_delete` mô phỏng crash sau 40 lần xóa.
- **Failure case 5 (bug thật, tìm được bằng test, đã sửa phía nhóm):** chạy evaluator chính thức `eval_t08` trên Windows báo `UnicodeDecodeError: 'charmap' codec can't decode byte 0x9d`. **Root cause:** `eval_t08` đọc `audit_log.jsonl` bằng `read_text()` không chỉ định encoding (cp1252 trên Windows), trong khi `AuditLog` ghi UTF-8 (`ensure_ascii=False`) kèm review note tiếng Việt. Nếu chấm trên máy Windows, PoC crash ngay ở bước chấm. **Sửa** (không đụng định nghĩa metric): `AuditLog` ghi JSON dạng ASCII (escape unicode), nội dung không đổi khi đọc lại. Test hồi quy: `test_audit_log_is_ascii_so_official_evaluator_reads_it_on_any_locale`. Đề xuất cho giảng viên: dùng `read_text(encoding='utf-8')` trong `eval_t08`.
- **Latency:** 1.00 s / 158 dòng trên CPU laptop (Intel64 Fam 6 Model 165, Windows 11, Python 3.13.5). Phần lớn thời gian là 126 lần checkpoint store, đổi tốc độ lấy khả năng resume.

## 07 · Human & decision

- **Review queue:** `out/poc/review_queue.csv` + `out/poc/contact_sheet.html` (offline, nút Export CSV). B = mọi exception (32), ưu tiên LEGAL_HOLD (1.0) > LEGAL_HOLD_INHERITED > IDENTITY > NO_PERMISSION > ORIGIN_UNKNOWN > MULTI_SUBJECT > lineage-only.
- **Quyết định người duyệt:** `reports/review_queue_reviewed.csv`. Reviewer daoquangtuan, 2026-11-14, 32/32 `approve`, mỗi dòng có `review_note`: giữ hold và hẹn xóa khi hết hold; redact/re-export artefact nhiều subject; data owner xác minh lineage embedding; chuyển vendor-x xóa backup a0156 và gửi bằng chứng. Pipeline đọc file qua `params.review_file`, nên clean clone vẫn tái lập.
- **Override + audit:** `edit`/`reject` + `override_value ∈ {delete, retain_legal_hold, escalate}`; **guard:** artefact legal hold không thể override thành `delete` (ghi `override_blocked`, test `test_reviewer_cannot_override_legal_hold_to_delete`). `out/poc/audit_log.jsonl` (append-only) có: 126 `plan:delete`, 28 `plan:escalate`, 4 `plan:retain_legal_hold`, 32 `review:approve`, 126 `mock_delete`, nghĩa là mọi action đều có audit entry.
- **Decision:** trước review là `HOLD` / `EXCEPTIONS_PENDING_REVIEW` (28 escalation chưa giải quyết). Sau review là `GO` / `REQUESTS_RESOLVED`, owner "daoquangtuan (Data Protection Lead)", metrics {delete 126, retain 4, escalate 28, unresolved 0} (`out/poc/decision.json`, `reports/decision_log.csv`).
- **SLA dashboard + notification stub (mốc +24h):** `out/poc/sla_report.csv` + `sla_dashboard.html` (offline). `as_of` chốt trong config là 2026-11-14 09:00 +07, nên chạy lại vẫn ra cùng kết quả. Trạng thái: OVERDUE (quá hạn, còn escalation), AT_RISK (≤ 7 ngày, còn escalation), ON_TRACK. Hiện 10/10 ON_TRACK (17–26 ngày còn lại) nhưng cả 10 là PARTIAL vì còn ticket redact/re-export. `notifications.jsonl` là outbox mock (26 tin, không gửi đi đâu): thông báo trạng thái cho từng subject, và yêu cầu hành động cho legal / acl-owner / data-owner / redaction-team theo reason_code.
- **Resume sau khi job bị ngắt (mốc +24h):** store được checkpoint atomic sau **mỗi** lần xóa; lần chạy sau bỏ qua tombstone đã có (xem failure case 4).
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

- `pytest`: **60 passed, 39 skipped** (skip = test cần GT giảng viên); riêng `tests/test_t08.py`: **13 passed**: audit log ASCII (hồi quy bug encoding), resume sau crash, SLA/notification, E2E + idempotency (chạy 2 lần cùng `actions.csv`, lần 2 toàn `already_deleted`), PoC > baseline, legal hold + backup, guard override, identity/ACL/origin/multi-subject, artefact mất tag, graph hỏng (trùng id, parent treo), review file cũ (exit 2), toggle ablation.
- Lệnh contract `python -m src.main --input fixtures/t08_deletion --config configs/lab.yaml --output out/contract --offline --seed 42` → exit 0.
- Máy: Windows 11 (10.0.26300), Intel64 Family 6 Model 165, Python 3.13.5 · git sha: xem tag `demo-180m`.

## 08b · Phân tích: legal hold vs quyền xóa · so sánh California DROP

> Tình huống học tập, không phải tư vấn pháp lý. Mục đánh dấu ⚑ cần đối chiếu văn bản gốc trước khi dùng.

**Legal hold vs quyền xóa (DR-002 / subj_03, DR-005 / subj_07).**
- Quyền xóa không tuyệt đối. GDPR Art.17(3) loại trừ trường hợp việc lưu giữ là cần thiết để tuân thủ **nghĩa vụ pháp lý** (điểm b) hoặc để **xác lập, thực hiện, bảo vệ yêu cầu pháp lý** (điểm e). Một legal hold (LH-2026-03, LH-2026-07) thuộc nhóm này. Luật 91/2025/QH15 cũng có các trường hợp ngoại lệ đối với quyền xóa ⚑ (đối chiếu số điều; NĐ 356/2025 hướng dẫn thi hành ⚑).
- **Ngoại lệ chỉ áp cho đúng phần dữ liệu cần giữ, không cho cả yêu cầu.** Vì vậy PoC vẫn xóa 12 artefact dẫn xuất của subj_03 và chỉ giữ raw + backup (`hold_scope=copies`). Đây là điểm pháp lý nhạy nhất (§06 failure 2): nếu lệnh hold bao cả dữ liệu dẫn xuất thì xóa chúng là hủy bằng chứng.
- **Giữ không có nghĩa là dùng tiếp.** Dữ liệu giữ vì hold nên bị **hạn chế xử lý** (tinh thần GDPR Art.18: chỉ lưu trữ, chỉ dùng cho yêu cầu pháp lý). PoC mới ghi `retain_legal_hold`, chưa khóa quyền truy cập: đây là gap.
- **Phải trả lời người yêu cầu và hẹn xóa.** GDPR Art.12(3): phản hồi trong 1 tháng, gia hạn thêm tối đa 2 tháng nếu phức tạp. PoC gửi thông báo trạng thái cho subject (`notifications.jsonl`) ghi rõ số artefact giữ theo nghĩa vụ pháp lý và "sẽ xóa khi hết hold". Mỗi dòng giữ có `reason_code` + hold id làm căn cứ. Chưa có job tự xóa khi hold được giải phóng.
- **Bên nhận dữ liệu cũng phải biết.** GDPR Art.19 yêu cầu thông báo việc xóa cho các bên đã nhận dữ liệu. Tương ứng trong PoC: backup a0156 thuộc ACL vendor-x → escalate + tin `acl-owner` yêu cầu vendor-x xóa và gửi bằng chứng; training export → ticket re-export.

**So sánh California DROP** (Delete Request and Opt-out Platform, theo Delete Act SB 362, do CPPA vận hành ⚑ mốc thời gian áp dụng):

| Khía cạnh | California DROP | PoC T08 |
|---|---|---|
| Phạm vi lan truyền | **Giữa các tổ chức:** một yêu cầu của người dân gửi tới mọi data broker đã đăng ký | **Trong một tổ chức:** một yêu cầu lan theo lineage tới mọi bản sao (raw → frame → crop → embedding, backup, export) |
| Cơ chế | Broker định kỳ kiểm tra danh sách yêu cầu và tự xử lý ⚑ chu kỳ | BFS trên data graph + luật ưu tiên, chạy lại idempotent |
| Bên thứ ba | Chính là đối tượng nhận yêu cầu | Chỉ thông báo (vendor-x, export); chưa có kênh nhận bằng chứng xóa từ bên ngoài |
| Bài học áp dụng | Một "điểm vào" duy nhất cho người dân, không bắt họ tự tìm từng nơi giữ dữ liệu | Nên mở rộng: xuất danh sách bên nhận (Art.19) và theo dõi xác nhận xóa của họ như một phần SLA |

## 09 · Limitations & ethics

- **Dev gold không độc lập với policy:** nhãn được soạn từ cùng spec `T08.md` (có hỗ trợ của trợ lý AI, labeller daoquangtuan duyệt), 1 labeller, N=48 (DR-008 thêm sau, cũng soạn theo spec nên không tăng tính độc lập, chỉ phủ thêm luật ACL). Kết quả 1.000 chỉ chứng minh code cài đúng cách hiểu spec. Điểm thật phụ thuộc hidden eval.
- **Rủi ro pháp lý:** phạm vi legal hold (§06 failure 2) và cách xử lý artefact nhiều subject cần DPO/legal xác nhận. Đây là tình huống học tập, **không** tuyên bố "đạt GDPR Art.17 / Luật 91/2025 / NĐ 356/2025".
- **Chưa làm:** gửi notification thật (mới là outbox mock); lịch xóa tự động khi hold hết hạn; theo dõi việc đóng ticket redact/re-export; xóa thật trên storage (mock).
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
| https://sites.research.google/datacardsplaybook/ (Data Cards Playbook) | ____ | Khung tài liệu hóa dataset (nguồn gốc, lineage, giới hạn); gợi ý ghi provenance và retention cho từng artefact |
| California Delete Act (SB 362) / DROP của CPPA (Research Shelf trong handout) | ____ | Một yêu cầu xóa lan tới mọi data broker đã đăng ký; dùng để so sánh ở §08b |

---

**Bảng 3 · Checklist chốt khi nộp**

- [x] Link repo và tag cuối `final-24h` trong report; input mẫu không chứa PII thật (fixture synthetic CC0). Slide demo: `demo/G08_T08_demo_slides.pdf`.
- [x] Đúng 1 lệnh run, 1 lệnh evaluate, 1 lệnh tests; không cần download khi chạy.
- [x] Có baseline/PoC metrics (dev gold), 3 failure case, reviewer evidence, decision log.
- [x] Có license/source provenance, seed, offline environment, GT/eval N.
- [x] Thành viên duy nhất có commit thực chất và được nêu trong bảng trên.

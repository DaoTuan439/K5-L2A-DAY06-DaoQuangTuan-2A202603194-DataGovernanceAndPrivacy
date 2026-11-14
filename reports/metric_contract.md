# Metric contract (khai báo bắt buộc — chốt ở phút 30, trước khi chạy eval)

> Các metric chuẩn đã được cài trong `src/metrics/tracks.py`. File này là nơi nhóm **cam kết** cách dùng chúng.
> Không đổi testset, threshold hay trọng số sau khi đã thấy kết quả eval.

| Mục | Khai báo của nhóm |
|---|---|
| Track | T08 · Retention & Delete Request Simulator |
| Primary metric (tên đúng như evaluator in ra) | `Deletion Completeness` |
| Tăng tốt hay giảm tốt? | higher |
| Đơn vị đánh giá (image / region / pair / release / batch / case …) | cặp (request_id, artefact_id) |
| Công thức + numerator / denominator | số artefact GT `expected_action = delete` mà ta ghi `delete` / tổng artefact GT `expected_action = delete` |
| Cách ghép prediction ↔ GT (IoU? id? tolerance?) | khớp chính xác theo khóa (request_id, artefact_id); cặp GT không có trong `actions.csv` = không xóa |
| Candidate pool cố định | 10 request trong `requests.json` × 212 artefact trong `data_graph.json` (mock-graph-1); hidden eval của giảng viên cùng cấu trúc |
| Review budget B / K | toàn bộ exception (mọi dòng `retain_legal_hold` / `escalate`, hiện 32 dòng); không có ngưỡng score |
| Seed | 42 (pipeline tất định, không dùng random) |
| Threshold policy (chọn trên dev như thế nào) | Không có ngưỡng số. Policy là luật ưu tiên cố định trong `src/t08_lineage.py`: legal hold → identity chưa xác minh → thiếu quyền ACL → origin unknown → nhiều subject → chỉ tìm thấy qua lineage → delete. Tham số chốt trong `configs/lab.yaml`: `hold_scope: copies`, `operator_role: data-platform`. Chọn từ yêu cầu nghiệp vụ trong `docs/tracks/T08.md` §8, **không** tune theo kết quả eval. |
| Eval split (không dùng để tune) | hidden eval do giảng viên sinh với seed bí mật; fixture chỉ để phát triển và tự kiểm (không có GT) |
| Chỉ số lỗi xấu (miss / false alarm / false reject) | **False-delete count** (mục tiêu 0: xóa nhầm exception hoặc xóa ngoài phạm vi request) là lỗi nghiêm trọng nhất. Miss (bỏ sót derived/backup) đo bằng Deletion Completeness. |
| Slices sẽ báo cáo (≥2) | (1) theo `expected_action` (delete / retain_legal_hold / escalate) do evaluator in; (2) theo `artefact_type` (raw_video, backup, frame, face_crop, embedding, annotation, training_export); (3) theo request |
| Cách báo độ bất định khi N nhỏ (Wilson CI / bootstrap) | Wilson 95% CI cho Deletion Completeness và Exception handling accuracy (N exception nhỏ, ~30); báo kèm count tuyệt đối (k/N) |
| Ngày giờ chốt + người chốt | 2026-11-14 · daoquangtuan (G08) |

Nếu baseline = 0 thì ghi rõ "baseline = 0" thay vì phần trăm cải thiện.

### Metric phụ (evaluator in sẵn)
- `False-delete count` (lower, mục tiêu 0)
- `Exception handling accuracy` = số dòng legal hold / escalate xử lý đúng / tổng số dòng đó
- `Audit trace completeness` = số action có entry trong `audit_log.jsonl` / tổng số action

### Giả định cần DPO / legal xác nhận
- Legal hold áp cho artefact bị hold **và bản sao chính xác** của nó (backup); dữ liệu dẫn xuất (frame, crop…) vẫn xóa được vì bản gốc làm bằng chứng đã được giữ. Ablation `hold_scope ∈ {self, copies, descendants}` sẽ được báo cáo.
- Artefact chứa nhiều subject → escalate (cần redact hoặc re-export) thay vì xóa, để không xóa dữ liệu của người khác.

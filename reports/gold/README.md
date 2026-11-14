# T08 dev gold set — protocol

**File:** `t08_dev_gold.csv` · **N = 48** cặp (request, artefact) · **Requests:** DR-002 (subj_03), DR-004 (subj_05), DR-008 (subj_11)
**Labeller:** daoquangtuan · **Ngày chốt:** 2026-11-14 · **Không phải điểm chính thức** (GT của giảng viên chỉ có ở hidden eval).

## Vì sao chọn 3 request này
- **DR-002**: raw video đang **legal hold** (LH-2026-03) → kiểm hold có lan sang backup / dữ liệu dẫn xuất hay không.
- **DR-004**: có **3 embedding origin unknown**, **frame/annotation 2 subject**, và nằm trong **2 training export**.
- **DR-008** (thêm sau): backup a0156 có **ACL `vendor-x`**, để phủ luật "thiếu quyền".
Ba request phủ 7/7 nhóm tình huống có trong fixture. Chưa phủ: request chưa xác minh danh tính, artefact mất tag (fixture không có).

## Cách tạo
1. Liệt kê ứng viên **từ dữ liệu thô, không dùng output pipeline**: mọi artefact gắn `subject_id` ∪ mọi hậu duệ của raw video của subject (BFS theo `parent_ids`).
2. Bảng nhãn chỉ chứa dữ kiện (type, subject_ids, parent, ACL, legal_hold, legal_hold của cha, origin_known). Không có cột action của pipeline.
3. Gán nhãn theo nhóm dữ kiện (cột `gold_group`), căn cứ `docs/tracks/T08.md` §3–§8, GDPR Art.17(3) và Luật 91/2025 (cột `gold_note`).

| Nhóm | Dữ kiện | Nhãn | N | Độ chắc |
|---|---|---|---|---|
| A | artefact có `legal_hold` | retain_legal_hold | 1 | high |
| B | backup của raw đang hold (bản thân không có trường hold) | retain_legal_hold | 1 | **medium** |
| C | frame/crop/embedding/annotation dẫn xuất từ raw đang hold | delete | 12 | **medium** |
| D | training_export nhiều subject | escalate | 4 | high |
| E | frame/annotation 2 subject | escalate | 2 | high |
| F | embedding `origin_known = False` | escalate | 3 | high |
| G | chỉ thuộc người yêu cầu, không ngoại lệ | delete | 24 | high |
| H | backup ACL vendor-x (operator không có quyền) | escalate | 1 | high |

## Hạn chế (phải nêu trong report)
- **DR-008 cũng do trợ lý AI soạn theo spec** (labeller daoquangtuan giao lại), nên không tăng tính độc lập; nó chỉ phủ thêm luật ACL.
- **Không độc lập với policy.** Nhãn và policy của pipeline cùng suy ra từ một spec (`T08.md`), nên khi PoC đạt 100% trên gold, điều đó chỉ chứng minh **pipeline cài đúng cách hiểu spec của nhóm**, không chứng minh cách hiểu đó khớp GT giảng viên.
- **Nhãn nhạy nhất là B và C** (phạm vi legal hold). Nếu GT coi hold chỉ áp cho chính artefact, thì B = delete (PoC mất 1 completeness). Nếu GT coi hold lan xuống mọi dẫn xuất, thì C = retain (PoC có 12 false-delete). Ablation `hold_scope` đo đúng rủi ro này.
- Chỉ 1 labeller, nên không đo được inter-annotator agreement. N nhỏ, vì vậy luôn báo Wilson 95% CI (`tools/t08_selfcheck.py`).

## Chạy
```bash
python -m tools.t08_selfcheck --pred out/baseline/actions.csv out/poc/actions.csv --out reports/selfcheck_t08.md
```

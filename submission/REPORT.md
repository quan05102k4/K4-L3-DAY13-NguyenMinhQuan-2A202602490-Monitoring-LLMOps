# Báo cáo cá nhân — K4-L3B Day 13 Monitoring & LLMOps

> Mỗi học viên hoàn thiện một file duy nhất này. Khi dẫn evidence, dùng đường dẫn tương đối, ví dụ `evidence/07-trace-waterfall.png`.

## 1. Thông tin học viên

- **Họ và tên:** Nguyễn Minh Quân
- **MSSV:** 2A202602490
- **Lớp:** K4-L3B
- **Repository URL:** https://github.com/quan05102k4/K4-L3-DAY13-NguyenMinhQuan-2A202602490-Monitoring-LLMOps
- **Commit SHA cuối:** `795bb9cf5c9ce0fb3ec06afb09e8c5fc3cec1c99` (commit code; tests ở ảnh 01 chạy trên commit này)
- **Challenge ID:** `day13-k4-l3b-monitoring-llmops-v1`
- **Tên project Langfuse cá nhân:** `day13-k4-l3b-2A202602490`

## 2. Evidence index

Điền đúng đường dẫn tới evidence thực tế. Có thể đổi tên hoặc dùng nhiều ảnh nếu cần.

| Evidence | Đường dẫn |
|---|---|
| Pytest cuối | [evidence/01-pytest.png](evidence/01-pytest.png) |
| Log validator | [evidence/02-log-validator.png](evidence/02-log-validator.png) |
| Dashboard validator | [evidence/03-dashboard-validator.png](evidence/03-dashboard-validator.png) |
| Structured log | [evidence/04-structured-log.png](evidence/04-structured-log.png) |
| PII redaction | [evidence/05-pii-redaction.png](evidence/05-pii-redaction.png) |
| Trace list | [evidence/06-trace-list.png](evidence/06-trace-list.png) |
| Trace waterfall | [evidence/07-trace-waterfall.png](evidence/07-trace-waterfall.png) |
| Trace metadata (root) | [evidence/08a-trace-metadata-root.png](evidence/08a-trace-metadata-root.png) |
| Trace metadata (generation) | [evidence/08b-trace-metadata-generation.png](evidence/08b-trace-metadata-generation.png) |
| Prompt versions | [evidence/09-prompt-versions.png](evidence/09-prompt-versions.png) |
| Prompt promote | [evidence/10a-prompt-promote.png](evidence/10a-prompt-promote.png) |
| Prompt rollback | [evidence/10b-prompt-rollback.png](evidence/10b-prompt-rollback.png) |
| Dashboard runtime | [evidence/11-dashboard-overview.png](evidence/11-dashboard-overview.png) |
| Incident metric | [evidence/12-incident-metric.png](evidence/12-incident-metric.png) |
| Incident log (metrics theo phút + request bất thường) | [evidence/13a-incident-log.png](evidence/13a-incident-log.png) |
| Incident log (log line `req-0410ee6b`) | [evidence/13b-incident-log.png](evidence/13b-incident-log.png) |
| Incident trace | [evidence/14-incident-trace.png](evidence/14-incident-trace.png) |

## 3. Kết quả kỹ thuật

| Nội dung | Baseline | Kết quả cuối | Nhận xét |
|---|---|---|---|
| `validate_logs.py` | 30/100 (20/21 record thiếu `correlation_id`/enrichment, 0 correlation ID) | 100/100 | Correlation ID, enrichment và scrub đều đạt; đo trên log sạch sau khi chuyển log baseline ra ngoài repo |
| `validate_dashboard.py` | HỢP LỆ 6/6 (contract có sẵn) | HỢP LỆ 6/6 | Contract giữ nguyên; dashboard runtime dựng bằng `scripts/build_dashboard.py` |
| `pytest` | 22 passed | 34 passed | Thêm 12 test: correlation ID, rò context, PII (CCCD/thẻ/passport/câu PII hỗn hợp), child observation |
| Số traces hợp lệ | 0 (chưa cấu hình key Langfuse, `tracing_enabled: false`) | 50 traces đủ cây root/retrieval/generation | 14 trace link prompt managed (`prompt_source=langfuse`); 36 trace trước khi tạo prompt ở `local-fallback` |
| Số PII leak | 0 (preview đã qua `summarize_text`, nhưng processor scrub chưa đăng ký) | 0 | Scrub mọi field trước khi ghi file; Langfuse không nhận Input/Output |
| Latency P95 / TTFT P95 | 187ms / 50ms (P50 150ms, 10 request, `/metrics`) | 1489ms / 50ms (P50 152ms) | P95 do 1/10 request đầu phải tải prompt từ Langfuse (cold cache); 9 request còn lại ~151-158ms |
| Retrieval success rate | 100% (10/10 `response_sent`, không có `request_failed`) | 100% | Practice `tool_fail` từng làm giảm còn 75.61% (error rate 24.39%), đã tắt |

## 4. Logging và PII

- **Cách tạo/nhận và truyền correlation ID:** [`app/middleware.py`](../app/middleware.py) gọi `clear_contextvars()` đầu mỗi request để context của request trước không rò sang. Nếu client gửi header `x-request-id` hợp lệ (chỉ ký tự `[A-Za-z0-9._-]`, tối đa 64, để tránh log injection) thì dùng lại, ngược lại sinh `req-` + 8 ký tự hex từ `uuid4`. ID được bind vào structlog contextvars, gán vào `request.state`, truyền vào `LabAgent.run` để đưa vào trace metadata, và trả lại trong header `x-request-id` cùng `x-response-time-ms`.
- **Các metadata được ghi vào structured log:** mọi dòng log có `ts` (UTC ISO), `level`, `service`, `event`, `correlation_id`. [`app/main.py`](../app/main.py) bind thêm `user_id_hash` (SHA-256 cắt 12 ký tự, không log user_id thô), `session_id`, `feature`, `model`, `env` trước dòng `request_received`. `response_sent` có thêm `latency_ms`, `ttft_ms`, `tokens_in`, `tokens_out`, `cost_usd`, `quality_score`, `tool_name`, `tool_success`; `request_failed` có `error_type`, `tool_name`, `tool_success`.
- **Cách bảo đảm PII được scrub trước khi ghi:** [`app/logging_config.py`](../app/logging_config.py) đăng ký `scrub_event` sau `format_exc_info` và **trước** `JsonlFileProcessor`/`JSONRenderer`, nên dữ liệu bị che trước khi serialize hay ghi file. `scrub_event` đệ quy qua mọi field (kể cả payload lồng nhau, list, error detail), không chỉ `payload`. [`app/pii.py`](../app/pii.py) có pattern email, CCCD, thẻ, điện thoại VN (`0`/`+84`, có dấu cách/chấm/gạch) và passport; lookaround `(?<!\d)`/`(?!\d)` ngăn che một phần của số dài hơn.
- **Cách kiểm chứng kết quả:** `validate_logs.py` đạt 100/100 (0 PII leak); gửi câu `a@b.vn 0901234567 001099012345 4111 1111 1111 1111` thì log ghi `[REDACTED_EMAIL] [REDACTED_PHONE_VN] [REDACTED_CCCD] [REDACTED_CREDIT_CARD]` (ảnh 05); tests [`tests/test_pii.py`](../tests/test_pii.py) và [`tests/test_correlation_logging.py`](../tests/test_correlation_logging.py) kiểm tra format ID, header, enrichment, không rò context giữa hai request và không có PII thô trong file log.

## 5. Tracing và prompt versioning

- **Cách xác nhận traces do chính tôi tạo trong project cá nhân:** key trong `.env` (không commit) thuộc project `day13-k4-l3b-2A202602490`; `/health` trả `tracing_enabled: true`; mỗi trace mang `correlation_id` trùng với request tôi gửi trong `data/logs.jsonl` (ví dụ `req-1a2b3c4d` ở ảnh 04 ↔ 08a). Đọc lại qua API `GET /api/public/v2/observations` của chính project: 50 traces `day13-agent-request`, tất cả đủ 3 observation.
- **Cấu trúc root/retrieval/generation observations:** trace `day13-agent-request` → root `lab-agent-run` (type `agent`) → hai con: `retrieval` (type `retriever`, `@observe` trên `retrieve()` trong [`app/mock_rag.py`](../app/mock_rag.py)) và `llm-generation` (type `generation`, `@observe` trên `FakeLLM.generate()` trong [`app/mock_llm.py`](../app/mock_llm.py)). Generation ghi `model`, `usage_details` (input/output/total), `cost_details` (input/output/total, cùng công thức với log) và `completion_start_time` (= TTFT). Tất cả dùng `capture_input=False, capture_output=False`; retrieval chỉ ghi `doc_count` và `query_preview` đã scrub trong metadata, nên Input/Output trên Langfuse trống.
- **Cách nối trace với log:** `propagate_attributes(metadata={"correlation_id": ...})` trong `LabAgent.run` gắn `correlation_id` vào trace và mọi observation con. Từ một dòng log, lọc Langfuse theo Metadata `correlation_id`; ngược lại, từ trace lấy `correlation_id` rồi lọc `data/logs.jsonl`. Giờ log là UTC, Langfuse hiển thị giờ Việt Nam (+7). Ví dụ ảnh 04 → 07/08: `req-1a2b3c4d`, log `ts=03:55:00Z` (10:55 trên Langfuse) ↔ trace `80f86f08c5082ad8c2482a2c6d507304` (`prompt_version=2` vì lúc đó `production` đang trỏ v2, giữa promote và rollback).
- **Prompt name:** `day13-chat` (type Text, biến `{{feature}}`, `{{docs}}`, `{{message}}`).
- **Version/label baseline:** v1 — `Feature={{feature}}` / `Docs={{docs}}` / `Question={{message}}`, label `baseline` (và `production` lúc đầu).
- **Version/label candidate:** v2 — thêm dòng `Answer concisely in at most 3 sentences, using only the Docs above.`, label `candidate`. Với cùng input, `tokens_in` tăng 32 → 49 (fake LLM trả cùng câu nên chỉ khác prompt version và token input).
- **Trace ID của mỗi version:**
  - v1 (label `baseline`, `req-b1b1b1b1`): `d9a6c3861ec4b75360fb1632321bdb6c`
  - v2 (label `candidate`, `req-c2c2c2c2`): `06d87b17e953c885ecfc5eb9f0fef775`
  - `production` → v1 trước promote (`req-a0a0a0a0`): `25771b2e3b50b81dc19fcbb08373f269`
  - `production` → v2 sau promote (`req-d3d3d3d3`): `87fd300d6dd3c45edd558e00ffe19a8f`
  - `production` → v1 sau rollback (`req-e4e4e4e4`): `077369e200320ff550b2ad03ffe39774`
- **Cách promote và rollback `production`:** code không đổi; app chỉ hỏi Langfuse theo `LANGFUSE_PROMPT_NAME`/`LANGFUSE_PROMPT_LABEL`. Promote = dời label `production` sang v2 (v1 tự mất label đó), restart API để bỏ cache prompt 60 giây, gửi 1 request và kiểm tra `prompt_version=2` (ảnh 10a). Rollback = dời `production` về v1, restart, gửi 1 request kiểm tra `prompt_version=1` (ảnh 10b). Generation trên Langfuse hiện link `Prompt: day13-chat - vN` nhờ `propagate_attributes(prompt=managed_prompt)`; prompt fallback không bao giờ được link.

## 6. Dashboard, SLO và alerts

- **Dashboard và sáu panel:** [`scripts/build_dashboard.py`](../scripts/build_dashboard.py) đọc `config/dashboard.yaml` (dùng lại `load_dashboard_config` của validator) và `data/logs.jsonl`, sinh `data/dashboard.html` (inline SVG, không phụ thuộc CDN hay thư viện ngoài requirements, time range 60 phút, `meta refresh` 30 giây, `--watch` để build lại liên tục). Sáu panel đúng contract: Latency (P50/P95/P99 + TTFT P95, threshold P95 ≤ 3000ms), Traffic (count, request/phút, ≥ 1), Errors (error rate %, breakdown `error_type`, retrieval success %, ≤ 2%), Cost (USD/phút và tổng, ≤ 2.5), Tokens (tổng `tokens_in`/`tokens_out`, ≤ 50000), Quality (mean `quality_score`, ≥ 0.75). Mỗi panel có đơn vị, đường threshold đỏ đứt nét, badge Đạt/Vượt ngưỡng và bảng dữ liệu theo phút. Retrieval success tính trên **mọi** event có `tool_success` (cả `response_sent` lẫn `request_failed`), không chỉ `request_failed`.
- **SLO và lý do chọn:** [`config/slo.yaml`](../config/slo.yaml) — `fast_successful_requests`: 99.5% request (`request_received`) kết thúc bằng `response_sent` với `latency_ms ≤ 3000` trong cửa sổ 28 ngày. Baseline P95 ~187ms nên 3000ms chừa headroom lớn cho LLM thật, và trùng threshold panel latency để SLO và dashboard nói cùng ngôn ngữ. Target 99.5% (không phải 99.9%) vì app phụ thuộc hai dependency ngoài (vector store, LLM provider).
- **Cách tính error budget:** budget = 100% − 99.5% = 0.5%, `allowed_bad = total × 0.005`. Với 10,000 request / 28 ngày → tối đa 50 request lỗi hoặc > 3000ms. Trong cửa sổ CP3 của tôi (25 request: 10 baseline, 5 challenge, 10 sau fix) có 1 request > 3000ms (`req-fe2a5417`, 3828ms) → bad ratio 4% = burn rate 8x; nếu kéo dài thì hết budget 28 ngày trong ~3.5 ngày. Chính sách: burn rate ≥ 14.4 trong 1h → page; ≥ 6 trong 6h → ticket; budget còn < 25% → dừng thay đổi prompt/model, chỉ rollback và sửa reliability.
- **Ba alert và runbook tương ứng:** [`config/alert_rules.yaml`](../config/alert_rules.yaml), runbook [`docs/alerts.md`](../docs/alerts.md); tất cả gửi Slack `#k4-l3b-alerts`, owner `student-2A202602490`, mỗi runbook có 3 bước Metrics → Logs → Traces và mitigation.
  1. `HighLatencyP95` (warning, 5m): P95 `latency_ms` > 2000ms — cảnh báo sớm trước ngưỡng SLO 3000ms ([runbook](../docs/alerts.md#alert-1)).
  2. `HighErrorRateOrRetrievalFailure` (critical, 5m): error rate > 2% hoặc retrieval success < 90% ([runbook](../docs/alerts.md#alert-2)).
  3. `CostPerRequestSpike` (warning, 15m): cost trung bình > 0.004 USD/request (~2x baseline 0.0019) hoặc tốc độ đốt > 2.5/24 USD/giờ ([runbook](../docs/alerts.md#alert-3)).

> Ví dụ cách viết error budget: "SLO 99.5% trong 28 ngày nghĩa là error budget 0.5%. Nếu workload có 10,000 request thì tối đa 50 request được phép lỗi hoặc chậm hơn ngưỡng SLO."

## 7. Điều tra challenge

- **Challenge ID:** `day13-k4-l3b-monitoring-llmops-v1` (cohort K4, 5 query; file Lab Coach gửi, lưu tại `config/challenge.json`, không commit).
- **Khoảng thời gian điều tra:** 2026-09-30, giờ Việt Nam: baseline 10:41 (03:41Z), sự cố 10:43:16–10:43:31 (03:43Z), sau fix 10:44 (03:44Z).
- **Triệu chứng từ metrics:** panel Latency: P95 `latency_ms` tăng từ 1469ms (baseline; 1 request đầu cold cache, các request khác ~440ms) lên **3828ms**; cả 5/5 request challenge vượt `latency_threshold_ms` = 2000ms của đề (2923–3828ms). TTFT P95 giữ nguyên 50ms; error rate 0%; retrieval success 100%; cost, tokens, quality không đổi. Chỉ có traffic feature `monitoring` trong cửa sổ này (ảnh 12, `scripts/investigate.py`).
- **Log line và correlation ID liên quan:** `response_sent` lúc `2026-09-30T03:43:25.763Z`, `correlation_id=req-0410ee6b`, `feature=monitoring`, `session_id=k4-l3b-challenge-s01`, `latency_ms=2951`, `ttft_ms=50`, `tokens_in=35`, `tokens_out=84`, `tool_success=true` (ảnh 13). Latency lấy từ log, không dùng thời gian phía client của `load_test.py` (12–15s do 5 request xếp hàng).
- **Trace ID và span gây ảnh hưởng:** trace `9f073e6b6e4d4a5d5b57e05adffd341e` (metadata `correlation_id=req-0410ee6b`): `lab-agent-run` 2952ms, trong đó **`retrieval` 2501ms**, `llm-generation` 152ms, không span nào lỗi (ảnh 14). So với trace baseline `d8fc2a558695d2c448f587462224f1e9` (`req-690a228e`): `retrieval` 0ms, `llm-generation` 152ms. Cả 5 trace challenge đều có `retrieval` = 2501ms.
- **Root cause:** bước retrieval (vector store/RAG) chậm thêm ~2.5s mỗi request, không lỗi và vẫn trả đủ `doc_count=1`. Generation, prompt và model không phải nguyên nhân: TTFT và thời gian generation giữ nguyên, token/cost không đổi. Ba lớp evidence cùng chỉ về một nguyên nhân: metric latency tăng nhưng TTFT không đổi → log `req-0410ee6b` chậm mà `tool_success=true` → trace cùng ID cho thấy thời gian nằm ở span `retrieval`.
- **Fix action:** khôi phục dependency retrieval (trong lab: `python scripts/inject_incident.py --scenario rag_slow --disable` lúc 03:44:45Z). Kiểm chứng: chạy lại load test, P95 về 1366ms ở phút 10:44 và span retrieval trở lại ~0ms.
- **Preventive measure:** (1) timeout cho retrieval (ví dụ 800ms) kèm fallback "không tìm thấy tài liệu" để một dependency chậm không kéo cả request; (2) cache kết quả retrieval cho câu hỏi lặp lại; (3) alert theo span: P95 thời gian `retrieval` > 500ms trong 5 phút, bổ sung cho `HighLatencyP95` vốn chỉ báo triệu chứng chung; (4) thêm vào runbook bước so sánh TTFT với latency để tách nhanh "chậm trước LLM" và "chậm ở LLM".

> Gợi ý cách viết ngắn, không thay cho evidence thực tế: "Metric cho thấy `[latency/error/cost/quality]` bất thường trong `[khoảng thời gian]`. Log line `[event]` có `correlation_id=[...]` đại diện cho request bị ảnh hưởng. Trace cùng `correlation_id` cho thấy span `[retrieval/generation/prompt/tool]` có dấu hiệu `[chậm/lỗi/token tăng]`. Root cause là `[nguyên nhân suy ra từ evidence]`. Fix action là `[hành động khôi phục]`; preventive measure là `[alert/runbook/test/guardrail để ngăn tái diễn]`."

## 8. Giải thích và tự đánh giá

- **Một quyết định kỹ thuật quan trọng và lý do:** đặt `@observe` trực tiếp trên `retrieve()` và `FakeLLM.generate()` và **không gửi Input/Output** nào lên Langfuse. Ban đầu tôi tạo child observation bằng helper trong `LabAgent` và gửi preview prompt đã scrub làm `input`; cách này làm public test `test_agent_prompt_trace.py` fail (client giả không có `update_current_generation`) và vẫn gửi prompt đã điền câu hỏi của user. Chuyển instrumentation về nơi định nghĩa hàm giúp `LabAgent.run` gần như giữ nguyên starter, public test pass mà không phải sửa, và link prompt chỉ đi qua `propagate_attributes(prompt=...)`. Chi phí được tính ở một chỗ (`estimate_cost` trong `mock_llm.py`) để log, metrics và Langfuse cùng một con số.
- **Một lỗi/blocker đã gặp:** (1) Pattern thẻ nuốt nhầm CCCD: với câu `... 001099012345 4111 1111 1111 1111`, log ra `[REDACTED_CREDIT_CARD] 1111 1111 1111` — mất nhãn CCCD và còn sót chuỗi số. (2) Sau khi bật tracing, P50 tăng từ 150ms lên ~440ms.
- **Cách tìm nguyên nhân và xử lý:** (1) Chạy thử đúng lệnh evidence 05 trước khi chụp; nguyên nhân là separator của pattern thẻ là tùy chọn nên `0010 9901 2345 4111` khớp 16 số. Đổi thứ tự để CCCD (12 số liền, có lookaround) chạy trước, thêm test cho đúng câu này. (2) Đi theo Metrics → Traces: `llm-generation` vẫn ~151ms nhưng `lab-agent-run` ~440ms; metadata cho thấy `prompt_source=local-fallback`, `prompt_fetch_error=LangfuseFallback` vì prompt `day13-chat` chưa tồn tại, và fallback không được cache nên request nào cũng gọi Langfuse. Sau khi tạo prompt, P50 về 152ms.
- **Cách hiểu luồng Metrics → Logs → Traces:** metrics trả lời *có vấn đề gì và từ lúc nào* (P95 3828ms lúc 10:43, TTFT không đổi, không lỗi); logs trả lời *request nào* (lọc `response_sent` có `latency_ms` > 2000 → `req-0410ee6b`); trace cùng `correlation_id` trả lời *bước nào* (`retrieval` 2501ms). `correlation_id` là khóa nối log với trace; trace ID chỉ nối các span trong một trace. Không mở trace ngẫu nhiên: metrics khoanh vùng thời gian và loại triệu chứng trước để chọn đúng request.
- **Vai trò của prompt version, token/cost, SLO hoặc rollback trong vận hành LLM:** prompt ảnh hưởng trực tiếp tới token, cost, latency và chất lượng nên phải có version và label như config; mỗi trace ghi `prompt_version` nên khi có regression có thể nối nó với lần đổi prompt, và rollback chỉ là dời label `production` mà không deploy code (v2 làm `tokens_in` tăng 32 → 49 trên cùng input). Token/cost cần theo dõi theo request vì cost có thể tăng mà traffic không tăng. SLO/error budget biến "nhanh và ổn" thành con số để quyết định khi nào được thay đổi prompt/model và khi nào phải dừng lại để sửa độ tin cậy.
- **Điều quan trọng nhất đã học:** kết luận chỉ đáng tin khi metric, log và trace cùng chỉ về một nguyên nhân; và bản thân observability cũng có chi phí (gọi Langfuse lấy prompt thêm ~300ms mỗi request khi fallback không được cache) nên cũng phải được đo.
- **Hạn chế hoặc phần chưa hoàn thành, nếu có:** (1) Endpoint `/chat` là `async` nhưng gọi hàm chặn (`time.sleep`), nên với `--concurrency 5` request xếp hàng: client thấy 12–15s trong khi `latency_ms` chỉ đo phần agent (~2.9s). Có thể sửa bằng `def` (threadpool) hoặc `asyncio.to_thread`; tôi giữ nguyên để không đổi hành vi challenge. (2) Evidence không chứng minh sự cố chỉ ảnh hưởng feature `monitoring`: trong cửa sổ đó chỉ có traffic `monitoring`. (3) Dashboard là HTML tĩnh build lại theo chu kỳ, chưa phải hệ thống giám sát live; alert rules mới ở mức định nghĩa, chưa nối Slack thật. (4) Quality score là heuristic, không đo chất lượng câu trả lời thật.

## 9. Checklist trước khi nộp

- [x] Kết quả và evidence thuộc commit SHA cuối.
- [x] Tất cả ảnh/output mở được bằng đường dẫn tương đối.
- [x] Incident evidence nối đúng metric → log → trace.
- [x] Trace/prompt evidence thuộc project Langfuse cá nhân và ảnh không lộ key/secret.
- [x] Repository chạy lại được theo README.
- [x] Không có secret, API key, PII thô hoặc evidence của người khác/lớp khác.
- [x] URL repo và commit SHA cuối đã được nộp trên LMS/Codelabs.

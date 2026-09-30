# Template Alert và Runbook

Mỗi alert phải dựa trên triệu chứng người dùng hoặc SLO, không dựa trực tiếp vào tên implementation nội bộ.

## Alert mẫu để tham khảo

Ví dụ dưới đây minh họa mức độ cụ thể cần có. Học viên không cần copy nguyên, nhưng ba alert trong bài nộp nên rõ ràng tương tự: điều kiện là gì, kéo dài bao lâu, ảnh hưởng tới user ra sao và người trực cần kiểm tra gì trước.

- Tên: `HighLatencyP95`
- Severity: `warning`
- Duration: `5m`
- Kênh thông báo: Slack `#k4-l3b-alerts`
- SLI/SLO liên quan: latency P95 của `response_sent.latency_ms`
- Điều kiện và thời gian duy trì: `p95(latency_ms) > 3000ms` trong 5 phút
- Ảnh hưởng tới người dùng: người dùng phải chờ lâu hơn trước khi nhận câu trả lời
- Ba bước kiểm tra đầu tiên:
  1. Mở dashboard latency để xác nhận P95/P99 và khoảng thời gian tăng.
  2. Lọc `data/logs.jsonl` trong khoảng đó, lấy một `correlation_id` có `latency_ms` cao.
  3. Mở trace cùng `correlation_id` trên Langfuse, so sánh các span chính để xác định bước nào bất thường.
- Mitigation tạm thời: dựa trên evidence thực tế để rollback prompt, khôi phục cấu hình liên quan, tắt practice scenario hoặc giảm tải khi demo.
- Owner: `student-<MSSV>`

## Alert 1

- Tên: `HighLatencyP95`
- Severity: `warning`
- Duration: `5m`
- Kênh thông báo: Slack `#k4-l3b-alerts`
- SLI/SLO liên quan: latency P95 của `response_sent.latency_ms`; SLO `fast_successful_requests` (99.5% request thành công và ≤ 3000ms / 28 ngày) trong [`config/slo.yaml`](../config/slo.yaml)
- Điều kiện và thời gian duy trì: `p95(latency_ms) > 2000ms` liên tục 5 phút (cảnh báo sớm, trước ngưỡng SLO 3000ms; baseline P95 ~190ms)
- Ảnh hưởng tới người dùng: người dùng chờ lâu hơn nhiều trước khi nhận câu trả lời; nếu kéo dài sẽ vượt SLO và đốt error budget
- Ba bước kiểm tra đầu tiên:
  1. Mở panel **Latency percentiles and TTFT**: xác định thời điểm P95/P99 tăng; so sánh TTFT P95. TTFT tăng → chậm ở LLM; latency tăng nhưng TTFT giữ nguyên (~50ms) → chậm trước bước LLM (retrieval/prompt fetch).
  2. Lọc log chậm trong khoảng đó, lấy `correlation_id`:
     `python -c "import json;[print(r['ts'],r['correlation_id'],r['latency_ms'],r['ttft_ms']) for r in map(json.loads,open('data/logs.jsonl',encoding='utf-8')) if r.get('event')=='response_sent' and r['latency_ms']>2000]"`
  3. Trên Langfuse, lọc trace theo metadata `correlation_id` đó, mở waterfall và so sánh duration của `retrieval` với `llm-generation`.
- Mitigation tạm thời: nếu span `retrieval` chậm → kiểm tra/khôi phục vector store, bật cache hoặc giảm top-k; nếu `llm-generation` chậm → rollback label `production` về prompt version trước (prompt dài hơn) hoặc chuyển model nhỏ hơn; khi demo thì tắt practice scenario `rag_slow`.
- Owner: `student-2A202602490`

## Alert 2

- Tên: `HighErrorRateOrRetrievalFailure`
- Severity: `critical`
- Duration: `5m`
- Kênh thông báo: Slack `#k4-l3b-alerts` (critical → page người trực)
- SLI/SLO liên quan: error rate = `request_failed / request_received`; retrieval success = `tool_success == true / tool_success != null`; guardrails `error_rate_pct_max: 2`, `retrieval_success_rate_pct_min: 90` và SLO `fast_successful_requests`
- Điều kiện và thời gian duy trì: error rate > 2% **hoặc** retrieval success < 90% liên tục 5 phút
- Ảnh hưởng tới người dùng: người dùng nhận HTTP 500 hoặc câu trả lời thiếu context; với SLO 99.5%, error rate 2% đốt budget nhanh gấp 4 lần mức cho phép
- Ba bước kiểm tra đầu tiên:
  1. Mở panel **Error rate and retrieval success**: xem `error_rate_pct`, `count_by_value` (loại lỗi) và `tool_success_rate_pct` để biết lỗi tập trung vào retrieval hay nơi khác.
  2. Lọc `event == "request_failed"` trong log, đọc `error_type`, `tool_name`, `payload.detail` và lấy một `correlation_id` (cũng có trong response header `x-request-id`).
  3. Mở trace có cùng `correlation_id`: span nào có level `ERROR` (vd. `retrieval` với `Vector store timeout`) và generation có được gọi hay không.
- Mitigation tạm thời: nếu lỗi ở retrieval → failover/restart vector store, tạm trả lời bằng fallback "không tìm thấy tài liệu" thay vì 500; nếu lỗi sau khi đổi prompt/model → rollback label `production`; tắt practice scenario `tool_fail` khi demo.
- Owner: `student-2A202602490`

## Alert 3

- Tên: `CostPerRequestSpike`
- Severity: `warning`
- Duration: `15m`
- Kênh thông báo: Slack `#k4-l3b-alerts`
- SLI/SLO liên quan: `response_sent.cost_usd` (panel Cost) và `tokens_in/tokens_out` (panel Tokens); guardrail `daily_cost_usd_max: 2.5`
- Điều kiện và thời gian duy trì: `avg(cost_usd) > 0.004 USD/request` (~2x baseline 0.0019) **hoặc** tốc độ đốt `sum(cost_usd)/giờ > 2.5/24 USD` liên tục 15 phút
- Ảnh hưởng tới người dùng: không làm hỏng request ngay nhưng vượt ngân sách vận hành; câu trả lời dài bất thường thường kéo theo latency và quality giảm
- Ba bước kiểm tra đầu tiên:
  1. So sánh panel **Cost over time** với **Request traffic**: cost tăng mà traffic không tăng → cost/request tăng, không phải do tải.
  2. Mở panel **Input and output tokens**: `tokens_out` tăng → output dài bất thường; `tokens_in` tăng → prompt/context phình. Lọc log `response_sent` có `tokens_out` cao, lấy `correlation_id`.
  3. Mở trace cùng `correlation_id`, xem `usage`/`cost` của `llm-generation` và `prompt_version` trong metadata để biết có trùng thời điểm đổi prompt/model không.
- Mitigation tạm thời: rollback label `production` về prompt version cũ nếu prompt mới gây output dài; đặt `max_tokens`, chuyển request đơn giản sang model rẻ hơn; tắt practice scenario `cost_spike` khi demo.
- Owner: `student-2A202602490`

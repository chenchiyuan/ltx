# Phase 1 API 调用示例

这些示例面向本地 Phase 1 web/control 节点，不包含真实 API Key。

## 环境变量

```bash
export LTX_BASE_URL="http://127.0.0.1:8000"
export LTX_API_KEY="<your-api-key>"
export LTX_ADMIN_TOKEN="<your-admin-token>"
```

## 文生视频

```bash
curl -sS -X POST "$LTX_BASE_URL/v1/video-generations" \
  -H "Authorization: Bearer $LTX_API_KEY" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: demo-t2v-001" \
  -d '{
    "mode": "text_to_video",
    "prompt": "a clean product shot of a glass teapot",
    "profile": "fast",
    "duration_seconds": 5,
    "aspect_ratio": "16:9"
  }'
```

## 上传图生视频输入图

```bash
curl -sS -X POST "$LTX_BASE_URL/v1/assets/uploads" \
  -H "Authorization: Bearer $LTX_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"filename":"input.png","content_type":"image/png","size_bytes":10}'
```

把返回的 `upload_url` 和 `asset_id` 保存后上传图片：

```bash
curl -sS -X PUT "$UPLOAD_URL" \
  -H "Authorization: Bearer $LTX_API_KEY" \
  --data-binary "@input.png"
```

## 图生视频

```bash
curl -sS -X POST "$LTX_BASE_URL/v1/video-generations" \
  -H "Authorization: Bearer $LTX_API_KEY" \
  -H "Content-Type: application/json" \
  -d "{
    \"mode\": \"image_to_video\",
    \"prompt\": \"slow camera movement\",
    \"image_asset_id\": \"$ASSET_ID\",
    \"profile\": \"fast\",
    \"duration_seconds\": 5,
    \"aspect_ratio\": \"16:9\"
  }"
```

## 查询状态和结果

```bash
curl -sS "$LTX_BASE_URL/v1/video-generations/$TASK_ID" \
  -H "Authorization: Bearer $LTX_API_KEY"

curl -sS "$LTX_BASE_URL/v1/video-generations/$TASK_ID/result" \
  -H "Authorization: Bearer $LTX_API_KEY"
```

## 本地触发一次 mock 执行

```bash
curl -sS -X POST "$LTX_BASE_URL/internal/dispatch/run-once" \
  -H "X-Admin-Token: $LTX_ADMIN_TOKEN"

curl -sS -X POST "$LTX_BASE_URL/internal/dispatch/complete-running" \
  -H "X-Admin-Token: $LTX_ADMIN_TOKEN"
```


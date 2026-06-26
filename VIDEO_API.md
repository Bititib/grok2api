# 视频生成接口文档 (面向第三方中转对接)

> **Base URL**: `https://api.yourdomain.com` (请替换为您的实际网关域名)  
> **认证方式**: `Authorization: Bearer <API_KEY>` (请在平台控制台生成并获取 API 密钥)

---

## 概述

本中继系统完全支持**用户请求 -> 转发第三方接口 -> 生成视频返回**的业务流。视频生成采用**异步模式**，调用流程分为两步：

```
① 提交任务 → ② 轮询状态并获取结果
   POST           GET
/v1/video/create  /v1/video/query?id={task_id}
```

---

## 1. 创建视频任务

```http
POST /v1/video/create
Content-Type: application/json
Authorization: Bearer <API_KEY>
```

### 请求参数 (JSON)

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `model` | string | ✅ | — | 视频模型名（见下方可用模型） |
| `prompt` | string | ✅ | — | 视频内容描述（建议用英语描述以获得最佳效果） |
| `seconds` | int | — | `6` | 时长，可选值: `6` 或 `10`。1.5 部分模型支持 `1-15` 的任意正整数 |
| `aspect_ratio` | string | — | `9:16` | 视频画幅比例，如 `"9:16"`、`"16:9"`、`"1:1"` |
| `size` | string | — | — | 可选，用于显式指定分辨率尺寸（如 `"720x1280"`、`"1280x720"`） |
| `images` | array | — | — | 参考图片数组，支持 `data:image/jpeg;base64,...` 的 Base64 格式，或图片的公网直链 URL。最多支持 7 张 |

### 可用模型

| 模型名 | 版本 | 支持模式 | 说明 | 推荐 |
|--------|------|----------|------|------|
| `grok-imagine-video` | 1.0 版本 | **文生视频** & **图生视频** | 标准视频生成（基于 1.0） | ⭐ 推荐 |
| `grok-imagine-video-1.5-preview` | 1.5 版本 | **仅支持 图生视频** | Grok 1.5 预览版，**必传 `images` 参数** (不支持纯文字生成) | ⭐⭐ 推荐 |
| `grok-imagine-video-1.5-fast` | 1.5 版本 | **文生视频** & **图生视频** | Grok 1.5 快速版，画质与速度均衡 | |
| `grok-imagine-1.0-video` | 1.0 版本 | **文生视频** & **图生视频** | 标准视频生成（可显式调用 1.0） | |

> [!IMPORTANT]
> **关于 `grok-imagine-video-1.5-preview` 模型限制说明**：
> 1.5-preview 模型属于**图生视频**专属模型。在调用时，必须在请求体中传入包含至少一张参考图片直链或 Base64 数据的 `images` 数组参数。如果仅传入 `prompt` 文字而没有提供参考图，API 接口将会直接报错并返回任务生成失败。


### 计费

视频生成根据生成时长与所选分辨率计费：

**1.0 版本视频模型 (如 grok-imagine-video / grok-imagine-1.0-video)**
- **480p**: `$0.02` / 秒 (生成失败不扣费)
- **720p**: `$0.03` / 秒 (生成失败不扣费)

**1.5 版本视频模型 (如 grok-imagine-video-1.5-preview / grok-imagine-video-1.5-fast)**
- **480p**: `$0.04` / 秒 (生成失败不扣费)
- **720p**: `$0.05` / 秒 (生成失败不扣费)

| 模型版本 | 分辨率 | 单价 | 6 秒 | 10 秒 | 20 秒 | 30 秒 |
|--------|--------|------|------|-------|-------|-------|
| 1.0 视频模型 | 480p | $0.02/秒 | $0.12 | $0.20 | $0.40 | $0.60 |
| | 720p | $0.03/秒 | $0.18 | $0.30 | $0.60 | $0.90 |
| 1.5 视频模型 | 480p | $0.04/秒 | $0.24 | $0.40 | $0.80 | $1.20 |
| | 720p | $0.05/秒 | $0.30 | $0.50 | $1.00 | $1.50 |

> 生成失败自动原路退回预扣除金额。

---

## 2. 调用示例

### 2.1 基础文字生成视频

**curl:**

```bash
curl -X POST https://api.yourdomain.com/v1/video/create \
  -H "Authorization: Bearer sk-你的Key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "grok-imagine-video-1.5-preview",
    "prompt": "A cute cat dancing on the moon, cinematic shot, sci-fi style, highly detailed",
    "seconds": 6,
    "aspect_ratio": "16:9"
  }'
```

**Python:**

```python
import requests

resp = requests.post(
    "https://api.yourdomain.com/v1/video/create",
    headers={
        "Authorization": "Bearer sk-你的Key",
        "Content-Type": "application/json"
    },
    json={
        "model": "grok-imagine-video-1.5-preview",
        "prompt": "A cute cat dancing on the moon, cinematic shot, sci-fi style, highly detailed",
        "seconds": 6,
        "aspect_ratio": "16:9"
    }
)
print(resp.json())
```

**响应成功:**

```json
{
  "id": "task_61be39094ee24240b27a09c673beb068",
  "status": "pending",
  "created": 1779357896
}
```

### 2.2 图生视频 (Image to Video)

将图片的 URL 作为参考输入，让模型将其转换为视频。

**curl:**

```bash
curl -X POST https://api.yourdomain.com/v1/video/create \
  -H "Authorization: Bearer sk-你的Key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "grok-imagine-video-1.5-preview",
    "prompt": "Animate this character running through the forest, dynamic camera action",
    "seconds": 6,
    "images": [
      "https://example.com/character.jpg"
    ]
  }'
```

---

## 3. 轮询视频任务状态

```http
GET /v1/video/query?id={task_id}
Authorization: Bearer <API_KEY>
```

提交任务后，建议下游客户端每隔 **5 秒**轮询一次此接口，直到 `status` 变为 `success` 或 `failed`。

**curl:**

```bash
curl "https://api.yourdomain.com/v1/video/query?id=task_61be39094ee24240b27a09c673beb068" \
  -H "Authorization: Bearer sk-你的Key"
```

### 任务状态字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 任务 ID |
| `status` | string | 状态：`pending`（排队中）、`processing`（生成中）、`success`（生成成功）、`failed`（失败） |
| `progress` | int | 视频生成百分比进度 (0 ~ 100) |
| `video_url` | string | 视频生成成功后的 MP4 下载直链 URL。若生成未完成或失败则为 `null` |
| `error` | string | 任务失败时的错误原因。若正常则为 `null` |

### 生成中响应

```json
{
  "id": "task_61be39094ee24240b27a09c673beb068",
  "status": "processing",
  "progress": 45,
  "video_url": null,
  "error": null
}
```

### 生成成功响应

```json
{
  "id": "task_61be39094ee24240b27a09c673beb068",
  "status": "success",
  "progress": 100,
  "video_url": "https://api.yourdomain.com/v1/files/video?id=video_61be39094ee24240b27a09c673beb068",
  "error": null
}
```

---

## 4. 兼容的对话接口生成视频 (OpenAI Chat Completions)

若您的客户端仅支持普通对话交互，本中继系统亦提供兼容 OpenAI Chat 接口的视频生成方案。

```http
POST /v1/chat/completions
Content-Type: application/json
Authorization: Bearer <API_KEY>
```

### 请求参数 (JSON)

```json
{
  "model": "grok-imagine-video-1.5-preview",
  "messages": [
    {
      "role": "user",
      "content": "Generate a beautiful forest scene in autumn"
    }
  ],
  "video_config": {
    "seconds": 6,
    "size": "720x1280",
    "preset": "normal"
  },
  "stream": true
}
```

### SSE 流式进度输出

系统将通过 Server-Sent Events 流式输出生成进度，最终吐出视频直链。

```text
data: {"id":"chatcmpl-xxx","object":"chat.completion.chunk","choices":[{"index":0,"delta":{"content":"[视频生成中] 进度: 15%...\n"},"finish_reason":null}]}

...

data: {"id":"chatcmpl-xxx","object":"chat.completion.chunk","choices":[{"index":0,"delta":{"content":"\n[视频生成成功]\n![Video](https://api.yourdomain.com/v1/files/video?id=video_61be39094ee24240b27a09c673beb068)"},"finish_reason":"stop"}]}
```

# Grok 视频生成 API 文档

> **Base URL**: `https://grokai.zhubo.asia`
> **认证方式**: `Authorization: Bearer <API_KEY>`

---

## 1. 概述

本系统是 Grok 视频生成上游 API 的中转站，对外提供与上游完全一致的接口规范。
视频生成采用**异步模式**：先提交任务拿到 ID，再轮询查询状态直到完成。

```
  ① POST 创建任务 → 返回 task ID
  ② GET  轮询状态 → status=completed 时获取视频 URL
```

### 1.1 本文档包含的模型

| Model ID | 主要用途 | 说明 |
| :--- | :--- | :--- |
| `grok-imagine-video-1.5-preview` | 图生视频 | 必须提供参考图 |
| `grok-imagine-1.0-video` | 文生视频 / 图生视频 | 只支持 6 秒或 10 秒 |
| `grok-imagine-video-1.5-fast` | 文生视频 / 图生视频 | 只支持 6 秒或 10 秒 |

### 1.2 计费

扣费在任务创建时预扣，失败自动退款。

| 模型系列 | 480p (SD) | 720p (HD) |
| :--- | :--- | :--- |
| 1.0 系列 | $0.02/秒 | $0.03/秒 |
| 1.5 系列 | $0.04/秒 | $0.05/秒 |

| 模型系列 | 分辨率 | 6 秒 | 10 秒 |
| :--- | :--- | :--- | :--- |
| 1.0 | 480p | $0.12 | $0.20 |
| 1.0 | 720p | $0.18 | $0.30 |
| 1.5 | 480p | $0.24 | $0.40 |
| 1.5 | 720p | $0.30 | $0.50 |

### 1.3 推荐轮询

创建任务后保存响应中的 `id`，每 5 到 10 秒查询一次任务状态。完成后读取 `video_url`、`url` 或 `result_url` 字段。

---

## 2. grok-imagine-video-1.5-preview

### 2.1 支持接口

| 接口 | 方法 | 用途 |
| :--- | :--- | :--- |
| `/v1/video/create` | POST | 统一视频创建接口，JSON 请求 |
| `/v1/video/query?id={VIDEO_ID}` | GET | 统一视频查询接口 |
| `/v1/videos` | POST | OpenAI 兼容视频创建接口，支持 JSON 或 multipart/form-data |
| `/v1/videos/{VIDEO_ID}` | GET | OpenAI 兼容视频查询接口 |
| `/v1/videos/{VIDEO_ID}/content` | GET | 下载视频内容 |

### 2.2 参数限制

| 参数 | 支持值 |
| :--- | :--- |
| seconds | 只支持 `6` 或 `10` |
| aspect_ratio | `9:16`、`16:9`、`1:1`、`2:3`、`3:2` |
| size / 清晰度 | `480P`、`720P`，也可用 `resolution` / `resolution_name` 传 `480p`、`720p`、`SD`、`HD` |
| 参考图 | ⚠️ **必须提供且只能 1 张**，通过 `images` 数组或 `input_reference` 传入 |

### 2.3 统一接口：POST /v1/video/create

```bash
curl -X POST "https://grokai.zhubo.asia/v1/video/create" \
  -H "Authorization: Bearer sk-你的Key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "grok-imagine-video-1.5-preview",
    "prompt": "Animate the subject in this image to walk forward with realistic wind blowing and dramatic cinematography, no subtitles",
    "aspect_ratio": "9:16",
    "size": "720P",
    "seconds": "10",
    "images": [
      "https://example.com/reference.jpg"
    ]
  }'
```

创建响应示例：

```json
{
  "id": "task_thXCjbedkZSUogxp1kQwdGM96Z2Hmkuj",
  "task_id": "task_thXCjbedkZSUogxp1kQwdGM96Z2Hmkuj",
  "object": "video",
  "model": "grok-imagine-video-1.5-preview",
  "status": "queued",
  "progress": 0,
  "created_at": 1782459124,
  "seconds": "10",
  "size": "720x1280"
}
```

### 2.4 查询：GET /v1/video/query

```bash
curl -X GET "https://grokai.zhubo.asia/v1/video/query?id=task_thXCjbedkZSUogxp1kQwdGM96Z2Hmkuj" \
  -H "Authorization: Bearer sk-你的Key"
```

完成响应示例：

```json
{
  "id": "task_thXCjbedkZSUogxp1kQwdGM96Z2Hmkuj",
  "object": "video",
  "status": "success",
  "model": "grok-imagine-video-1.5-preview",
  "progress": 100,
  "seconds": "10",
  "size": "720x1280",
  "quality": "standard",
  "url": "https://grokai.zhubo.asia/v1/files/video?id=task_thXCjbedkZSUogxp1kQwdGM96Z2Hmkuj",
  "video_url": "https://grokai.zhubo.asia/v1/files/video?id=task_thXCjbedkZSUogxp1kQwdGM96Z2Hmkuj",
  "result_url": "https://grokai.zhubo.asia/v1/files/video?id=task_thXCjbedkZSUogxp1kQwdGM96Z2Hmkuj"
}
```

### 2.5 OpenAI 兼容接口：POST /v1/videos

JSON 请求：

```bash
curl -X POST "https://grokai.zhubo.asia/v1/videos" \
  -H "Authorization: Bearer sk-你的Key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "grok-imagine-video-1.5-preview",
    "prompt": "Animate the reference image with natural motion, cinematic lighting, no subtitles",
    "seconds": 10,
    "aspect_ratio": "16:9",
    "resolution": "HD",
    "images": [
      "https://example.com/reference.jpg"
    ]
  }'
```

multipart/form-data 请求：

```bash
curl -X POST "https://grokai.zhubo.asia/v1/videos" \
  -H "Authorization: Bearer sk-你的Key" \
  -F "model=grok-imagine-video-1.5-preview" \
  -F "prompt=Animate the reference image with natural motion, cinematic lighting, no subtitles" \
  -F "seconds=10" \
  -F "size=16:9" \
  -F "resolution_name=720p" \
  -F "input_reference=https://example.com/reference.jpg"
```

---

## 3. grok-imagine-1.0-video

### 3.1 支持接口

| 接口 | 方法 | 用途 |
| :--- | :--- | :--- |
| `/v1/videos` | POST | OpenAI 兼容视频创建接口，支持 JSON 或 multipart/form-data |
| `/v1/videos/{VIDEO_ID}` | GET | 查询任务 |
| `/v1/videos/{VIDEO_ID}/content` | GET | 下载视频内容 |
| `/v1/video/create` | POST | 统一视频创建接口，JSON 请求 |
| `/v1/video/query?id={VIDEO_ID}` | GET | 统一视频查询接口 |

### 3.2 参数限制

| 参数 | 支持值 |
| :--- | :--- |
| seconds | 只支持 `6` 或 `10` |
| size / aspect_ratio | `9:16`、`16:9`、`1:1`、`2:3`、`3:2`，也支持实际尺寸 `720x1280`、`1280x720`、`1024x1024`、`1024x1792`、`1792x1024` |
| 清晰度 | `480P`、`720P`、`480p`、`720p`、`SD`、`HD` |
| 参考图 | 文生视频可不传；图生视频可传 `input_reference`、`input_references`、`reference_images` 或 `images` |

### 3.3 OpenAI 兼容接口：POST /v1/videos

文生视频，multipart/form-data：

```bash
curl -X POST "https://grokai.zhubo.asia/v1/videos" \
  -H "Authorization: Bearer sk-你的Key" \
  -F "model=grok-imagine-1.0-video" \
  -F "prompt=A cinematic travel video of mountains under golden sunset, smooth drone movement, no subtitles" \
  -F "seconds=10" \
  -F "size=16:9" \
  -F "resolution_name=720p"
```

图生视频，multipart/form-data：

```bash
curl -X POST "https://grokai.zhubo.asia/v1/videos" \
  -H "Authorization: Bearer sk-你的Key" \
  -F "model=grok-imagine-1.0-video" \
  -F "prompt=Animate the reference image with gentle wind and natural camera motion, no subtitles" \
  -F "seconds=6" \
  -F "size=9:16" \
  -F "resolution_name=720p" \
  -F "input_reference=https://example.com/reference.jpg"
```

JSON 图生视频：

```bash
curl -X POST "https://grokai.zhubo.asia/v1/videos" \
  -H "Authorization: Bearer sk-你的Key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "grok-imagine-1.0-video",
    "prompt": "Animate the reference image with gentle wind and natural camera motion, no subtitles",
    "seconds": 6,
    "aspect_ratio": "9:16",
    "resolution": "HD",
    "input_reference": "https://example.com/reference.jpg"
  }'
```

创建响应示例：

```json
{
  "id": "video_xxx",
  "object": "video",
  "created_at": 1780000000,
  "status": "queued",
  "model": "grok-imagine-1.0-video",
  "progress": 0,
  "prompt": "Animate the reference image with gentle wind and natural camera motion, no subtitles",
  "seconds": "6",
  "size": "720x1280",
  "quality": "standard"
}
```

### 3.4 查询：GET /v1/videos/{VIDEO_ID}

```bash
curl -X GET "https://grokai.zhubo.asia/v1/videos/VIDEO_ID" \
  -H "Authorization: Bearer sk-你的Key"
```

完成响应示例：

```json
{
  "id": "video_xxx",
  "object": "video",
  "status": "completed",
  "model": "grok-imagine-1.0-video",
  "progress": 100,
  "seconds": "6",
  "size": "720x1280",
  "url": "https://grokai.zhubo.asia/v1/files/video?id=video_xxx",
  "video_url": "https://grokai.zhubo.asia/v1/files/video?id=video_xxx",
  "result_url": "https://grokai.zhubo.asia/v1/files/video?id=video_xxx"
}
```

### 3.5 统一接口：POST /v1/video/create

文生视频示例：

```bash
curl -X POST "https://grokai.zhubo.asia/v1/video/create" \
  -H "Authorization: Bearer sk-你的Key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "grok-imagine-1.0-video",
    "prompt": "A cinematic shot of a futuristic city at sunrise, slow camera push-in, no subtitles",
    "aspect_ratio": "16:9",
    "size": "720P",
    "seconds": "10",
    "images": []
  }'
```

单图生视频示例：

```bash
curl -X POST "https://grokai.zhubo.asia/v1/video/create" \
  -H "Authorization: Bearer sk-你的Key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "grok-imagine-1.0-video",
    "prompt": "Make the subject walk forward slowly, natural daylight, no subtitles",
    "aspect_ratio": "9:16",
    "size": "720P",
    "seconds": "6",
    "images": [
      "https://example.com/reference.jpg"
    ]
  }'
```

---

## 4. grok-imagine-video-1.5-fast

### 4.1 支持接口

| 接口 | 方法 | 用途 |
| :--- | :--- | :--- |
| `/v1/videos` | POST | OpenAI 兼容视频创建接口，支持 JSON 或 multipart/form-data |
| `/v1/videos/{VIDEO_ID}` | GET | 查询任务 |
| `/v1/videos/{VIDEO_ID}/content` | GET | 下载视频内容 |
| `/v1/video/create` | POST | 统一视频创建接口，JSON 请求 |
| `/v1/video/query?id={VIDEO_ID}` | GET | 统一视频查询接口 |

### 4.2 参数限制

| 参数 | 支持值 |
| :--- | :--- |
| seconds | 只支持 `6` 或 `10` |
| size / aspect_ratio | `9:16`、`16:9`、`1:1`、`2:3`、`3:2`，也支持实际尺寸 `720x1280`、`1280x720`、`1024x1024`、`1024x1792`、`1792x1024` |
| 清晰度 | `480P`、`720P`、`480p`、`720p`、`SD`、`HD` |
| 参考图 | 文生视频可不传；图生视频可传 `input_reference`、`input_references`、`reference_images` 或 `images` |

### 4.3 OpenAI 兼容接口示例

文生视频：

```bash
curl -X POST "https://grokai.zhubo.asia/v1/videos" \
  -H "Authorization: Bearer sk-你的Key" \
  -F "model=grok-imagine-video-1.5-fast" \
  -F "prompt=A cinematic travel video of mountains under golden sunset, smooth drone movement, no subtitles" \
  -F "seconds=10" \
  -F "size=16:9" \
  -F "resolution_name=720p"
```

图生视频：

```bash
curl -X POST "https://grokai.zhubo.asia/v1/videos" \
  -H "Authorization: Bearer sk-你的Key" \
  -F "model=grok-imagine-video-1.5-fast" \
  -F "prompt=Animate the reference image with gentle wind and natural camera motion, no subtitles" \
  -F "seconds=6" \
  -F "size=9:16" \
  -F "resolution_name=720p" \
  -F "input_reference=https://example.com/reference.jpg"
```

JSON 示例：

```bash
curl -X POST "https://grokai.zhubo.asia/v1/videos" \
  -H "Authorization: Bearer sk-你的Key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "grok-imagine-video-1.5-fast",
    "prompt": "Animate the reference image with gentle wind and natural camera motion, no subtitles",
    "seconds": 6,
    "aspect_ratio": "9:16",
    "resolution": "HD",
    "images": [
      "https://example.com/reference.jpg"
    ]
  }'
```

### 4.4 统一接口示例

```bash
curl -X POST "https://grokai.zhubo.asia/v1/video/create" \
  -H "Authorization: Bearer sk-你的Key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "grok-imagine-video-1.5-fast",
    "prompt": "A cinematic shot of a futuristic city at sunrise, slow camera push-in, no subtitles",
    "aspect_ratio": "16:9",
    "size": "720P",
    "seconds": "10",
    "images": []
  }'
```

查询：

```bash
curl -X GET "https://grokai.zhubo.asia/v1/video/query?id=VIDEO_ID" \
  -H "Authorization: Bearer sk-你的Key"
```

---

## 5. 请求体兼容说明

### 5.1 JSON 可用字段

`/v1/videos` 和 `/v1/video/create` 支持从以下字段解析视频参数：

| 语义 | 可用字段 |
| :--- | :--- |
| 模型 | `model` |
| 提示词 | `prompt` |
| 时长 | `seconds`、`duration`、`video_length`、`video_config.video_length`、`video_config.duration`、`video_config.seconds` |
| 画幅 | `aspect_ratio`、`video_config.aspect_ratio` |
| 尺寸 | `size`、`video_config.size` |
| 清晰度 | `resolution`、`resolution_name`、`video_config.resolution`、`video_config.resolution_name` |
| 参考图 | `input_reference`、`input_references`、`reference_images`、`images` |

### 5.2 multipart/form-data 可用字段

| 字段 | 说明 |
| :--- | :--- |
| `model` | 模型名 |
| `prompt` | 视频提示词 |
| `seconds` | 时长 |
| `size` | 可传实际尺寸或比例，例如 `720x1280`、`1280x720`、`9:16`、`16:9` |
| `aspect_ratio` | 部分接口支持独立传比例 |
| `resolution_name` | `480p` 或 `720p` |
| `preset` | 可选，常见值 `normal`、`fun`、`spicy`、`custom` |
| `input_reference` | 参考图 URL |
| `input_reference[]` | 参考图文件上传 |

---

## 6. 错误处理建议

| 错误 | 常见原因 | 建议 |
| :--- | :--- | :--- |
| `seconds must be one of ...` | 时长不支持 | 按对应模型限制传参（只支持 6 或 10） |
| `requires an input image` | `grok-imagine-video-1.5-preview` 未传参考图 | 补充 `images` 或 `input_reference` |
| `images must contain exactly one image URL` | 1.5-preview 的 `/v1/video/create` 传了 0 张或多张图 | 只传 1 个公网图片 URL |
| `Image URL could not be fetched` | 上游无法下载参考图 | 确认图片 URL 可公网访问，返回真实 JPG/PNG/WebP |
| `Asset upload returned 403` | 上游拒绝参考图上传或图片特征触发限制 | 更换图片、降低图片复杂度或转存后重试 |
| `No available accounts for video generation` | 当前无可用生成账号 | 稍后重试或检查账号池 |

# Grok 视频生成中继接口文档 (面向第三方对接与转发)

> **Base URL**: `https://api.yourdomain.com` (使用时请替换为您的实际网关域名)  
> **认证方式**: `Authorization: Bearer <API_KEY>` (请在平台控制台生成并获取 API 密钥)

---

## 1. 概述

本中继系统支持完整的 **用户请求 -> 中转网关 -> 转发第三方 API -> 异步生成视频 -> 返回视频结果** 业务流程。
视频生成采用**异步非阻塞模式**，核心调用逻辑分为两步：
1. **第一步：提交任务** (发送 `POST` 请求创建任务，系统扣费并返回任务 ID)
2. **第二步：轮询状态** (发送 `GET` 请求轮询状态，系统检测到成功时返回视频 URL，失败时则自动回滚扣费)

```
       ① 提交任务 (扣费并生成任务) → ② 轮询状态并获取结果 (查询任务详情)
                 POST                                     GET
        /v1/video/create                     /v1/video/query?id={task_id}
        /v1/videos                           /v1/videos/{task_id}
```

---

### 1.1 支持的模型列表

| 模型标识 (Model ID) | 模型版本 | 主要用途 | 必须参数与输入限制说明 | 推荐指数 |
| :--- | :--- | :--- | :--- | :--- |
| **`grok-imagine-video-1.5-preview`** | 1.5 预览版 | **仅支持图生视频** | ⚠️ **必须提供输入参考图**。请求体中必须传入 `images` 或相应参数，且只能包含 1 张图片，**不支持纯文字生成**。 | ⭐⭐⭐ |
| **`grok-imagine-video-1.5-fast`** | 1.5 快速版 | 文生视频 / 图生视频 | 时长仅支持 `6` 或 `10` 秒。兼顾画质与生成速度。 | ⭐⭐ |
| **`grok-imagine-video`** | 1.0 标准版 | 文生视频 / 图生视频 | 默认经典版模型，时长只支持 `6` 或 `10` 秒。 | ⭐ |
| **`grok-imagine-1.0-video`** | 1.0 显式版 | 文生视频 / 图生视频 | 显式指定调用 1.0 版本模型，时长只支持 `6` 或 `10` 秒。 | ⭐ |

---

### 1.2 计费机制

扣费在**任务创建时进行预扣除**，如果任务**生成失败或被取消，系统会自动执行原路退款**，将额度回滚至用户账户中。

* **1.0 版本系列模型** (`grok-imagine-video` / `grok-imagine-1.0-video`)
  * **480p / SD 分辨率**: `$0.02` / 秒
  * **720p / HD 分辨率**: `$0.03` / 秒
* **1.5 版本系列模型** (`grok-imagine-video-1.5-preview` / `grok-imagine-video-1.5-fast`)
  * **480p / SD 分辨率**: `$0.04` / 秒
  * **720p / HD 分辨率**: `$0.05` / 秒

#### 预估计费对照表：

| 模型版本 | 分辨率 (Size/Res) | 秒单价 | 6 秒视频 | 10 秒视频 | 12 秒视频 | 15 秒视频 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1.0 系列模型** | 480p (SD) | `$0.02`/秒 | `$0.12` | `$0.20` | *不支持* | *不支持* |
| | 720p (HD) | `$0.03`/秒 | `$0.18` | `$0.30` | *不支持* | *不支持* |
| **1.5 系列模型** | 480p (SD) | `$0.04`/秒 | `$0.24` | `$0.40` | `$0.48` | `$0.60` |
| | 720p (HD) | `$0.05`/秒 | `$0.30` | `$0.50` | `$0.60` | `$0.75` |

---

### 1.3 轮询策略建议
* 创建任务成功后，应妥善保存响应 JSON 中的 `id` (即任务 ID)。
* 建议客户端**每隔 5 ~ 10 秒**向查询接口发起一次 GET 请求。
* 当返回的 `status` 为 `completed` 或 `success` 时，即可停止轮询并直接读取返回的 `video_url`、`url` 或 `result_url` 获取生成的视频 MP4 下载直链。

---

## 2. grok-imagine-video-1.5-preview (1.5 预览版详细指南)

Grok 1.5 视频预览版模型拥有大幅提升的连贯性和光影效果，属于高端生成模型，**仅支持图生视频**。

### 2.1 支持的路由接口

* `POST /v1/video/create` —— **【推荐】统一视频创建 JSON 接口**
* `GET /v1/video/query?id={task_id}` —— **【推荐】统一视频状态查询接口**
* `POST /v1/videos` —— OpenAI 兼容视频创建接口 (支持 JSON 或 multipart/form-data)
* `GET /v1/videos/{task_id}` —— OpenAI 兼容视频状态查询接口
* `GET /v1/videos/{task_id}/content` —— 下载生成的 MP4 视频媒体内容文件

### 2.2 参数限制与说明

* **`seconds` (时长)**: 支持 `1` 到 `15` 的任意整数秒（如 6、10、12 等）。
* **`aspect_ratio` (画幅比例)**: 支持 `9:16`、`16:9`、`1:1`、`2:3`、`3:2`。
* **`size` (清晰度)**: 接收 `480P` 或 `720P`。也可以通过参数 `resolution` 或 `resolution_name` 传递 `480p`、`720p`、`SD`、`HD`。
* **参考图限制**: ⚠️ **必须提供 1 张输入参考图**。在统一 JSON 接口请求中，`images` 数组必须且只能包含 1 个有效的公网图片 URL。
* **画幅比到分辨率映射关系**：

| aspect_ratio | 输出的实际像素尺寸 (size) | 常见画面方向 |
| :--- | :--- | :--- |
| **`9:16`** | 720x1280 | 竖屏 (手机、短视频常用) |
| **`16:9`** | 1280x720 | 横屏 (电视、电影、网页常用) |
| **`1:1`** | 1024x1024 | 正方形 (社交媒体) |
| **`2:3`** | 720x1280 | 竖屏 |
| **`3:2`** | 1280x720 | 横屏 |

### 2.3 推荐的统一创建接口：`POST /v1/video/create`

本接口接收标准 JSON 数据，更不容易出现表单编码错误。

#### 请求字段说明：

| 字段 | 类型 | 是否必填 | 默认值 | 字段说明 |
| :--- | :--- | :--- | :--- | :--- |
| **`model`** | string | ✅ 是 | — | 固定传值：`grok-imagine-video-1.5-preview` |
| **`prompt`** | string | ✅ 是 | — | 描述图片应如何动起来、镜头如何推拉或场景补充描述。 |
| **`aspect_ratio`** | string | 否 | `9:16` | 视频画面比例。可选：`9:16`、`16:9`、`1:1`、`2:3`、`3:2` |
| **`size`** | string | 否 | `720P` | 清晰度等级。可选：`480P`、`720P` |
| **`seconds`** | number/str | ✅ 是 | `6` | 视频时长，取值范围 `1` 到 `15` |
| **`images`** | array[str] | ✅ 是 | — | **必须传 1 个且仅包含 1 个元素的图片直链 URL 数组**。例如：`["https://example.com/reference.jpg"]` |

#### 请求示例 (curl)：

```bash
curl -X POST "https://api.yourdomain.com/v1/video/create" \
  -H "Authorization: Bearer sk-你的Key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "grok-imagine-video-1.5-preview",
    "prompt": "Animate the subject in this image to walk forward with realistic wind blowing and dramatic cinematography, no watermark",
    "aspect_ratio": "9:16",
    "size": "720P",
    "seconds": 10,
    "images": [
      "https://example.com/reference.jpg"
    ]
  }'
```

#### 响应示例 (成功创建)：

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

### 2.4 查询任务：`GET /v1/video/query`

#### 请求示例 (curl)：

```bash
curl -X GET "https://api.yourdomain.com/v1/video/query?id=task_thXCjbedkZSUogxp1kQwdGM96Z2Hmkuj" \
  -H "Authorization: Bearer sk-你的Key"
```

#### 成功完成响应示例：

```json
{
  "id": "task_thXCjbedkZSUogxp1kQwdGM96Z2Hmkuj",
  "object": "video",
  "status": "success",
  "model": "grok-imagine-video-1.5-preview",
  "progress": 100,
  "prompt": "Animate the subject in this image to walk forward with realistic wind blowing and dramatic cinematography, no watermark",
  "seconds": "10",
  "size": "720x1280",
  "quality": "standard",
  "url": "https://api.yourdomain.com/v1/files/video?id=task_thXCjbedkZSUogxp1kQwdGM96Z2Hmkuj",
  "video_url": "https://api.yourdomain.com/v1/files/video?id=task_thXCjbedkZSUogxp1kQwdGM96Z2Hmkuj",
  "result_url": "https://api.yourdomain.com/v1/files/video?id=task_thXCjbedkZSUogxp1kQwdGM96Z2Hmkuj"
}
```

### 2.5 OpenAI 兼容接口：`POST /v1/videos`

#### JSON 格式请求示例：

```bash
curl -X POST "https://api.yourdomain.com/v1/videos" \
  -H "Authorization: Bearer sk-你的Key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "grok-imagine-video-1.5-preview",
    "prompt": "Animate the reference image with natural motion, cinematic lighting",
    "seconds": 10,
    "aspect_ratio": "16:9",
    "resolution": "HD",
    "images": [
      "https://example.com/reference.jpg"
    ]
  }'
```

#### Multipart 表单格式请求示例 (`multipart/form-data`)：

```bash
curl -X POST "https://api.yourdomain.com/v1/videos" \
  -H "Authorization: Bearer sk-你的Key" \
  -F "model=grok-imagine-video-1.5-preview" \
  -F "prompt=Animate the reference image with natural motion, cinematic lighting" \
  -F "seconds=10" \
  -F "size=16:9" \
  -F "resolution_name=720p" \
  -F "input_reference=https://example.com/reference.jpg"
```

---

## 3. grok-imagine-1.0-video (1.0 经典版详细指南)

这是系统的标准视频生成模型，支持通过文字生成视频，亦支持通过图片进行视频渲染。

### 3.1 支持的路由接口
* `POST /v1/video/create` —— 统一视频创建 JSON 接口
* `GET /v1/video/query?id={task_id}` —— 统一视频状态查询接口
* `POST /v1/videos` —— OpenAI 兼容创建接口
* `GET /v1/videos/{task_id}` —— OpenAI 兼容状态查询接口

### 3.2 参数限制与说明
* **`seconds` (时长)**: **只支持 `6` 或 `10` 秒**。传入其他时长参数将无法被模型处理。
* **`aspect_ratio` / `size`**: 支持画幅比 `"9:16"`、`"16:9"`、`"1:1"`、`"2:3"`、`"3:2"`。亦支持直接传输出分辨率，如 `"720x1280"`、`"1280x720"`、`"1024x1024"`、`"1024x1792"`、`"1792x1024"`。
* **清晰度 (Resolution)**: 可用参数传 `480P`、`720P`、`480p`、`720p`、`SD`、`HD`。
* **参考图参数**: 
  * 纯文字生成视频 (Text-to-Video)：不需要提供任何图片。
  * 图生视频 (Image-to-Video)：可以传图，输入参数名支持 `input_reference`、`input_references`、`reference_images` 或 `images`。

### 3.3 OpenAI 兼容接口示例 (`POST /v1/videos`)

#### 文生视频示例 (Multipart 表单)：
```bash
curl -X POST "https://api.yourdomain.com/v1/videos" \
  -H "Authorization: Bearer sk-你的Key" \
  -F "model=grok-imagine-1.0-video" \
  -F "prompt=A cinematic travel video of mountains under golden sunset, smooth drone movement" \
  -F "seconds=10" \
  -F "size=16:9" \
  -F "resolution_name=720p"
```

#### 图生视频示例 (Multipart 表单)：
```bash
curl -X POST "https://api.yourdomain.com/v1/videos" \
  -H "Authorization: Bearer sk-你的Key" \
  -F "model=grok-imagine-1.0-video" \
  -F "prompt=Animate the reference image with gentle wind and natural camera motion" \
  -F "seconds=6" \
  -F "size=9:16" \
  -F "resolution_name=720p" \
  -F "input_reference=https://example.com/reference.jpg"
```

#### 图生视频示例 (JSON 格式)：
```bash
curl -X POST "https://api.yourdomain.com/v1/videos" \
  -H "Authorization: Bearer sk-你的Key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "grok-imagine-1.0-video",
    "prompt": "Animate the reference image with gentle wind and natural camera motion",
    "seconds": 6,
    "aspect_ratio": "9:16",
    "resolution": "HD",
    "input_reference": "https://example.com/reference.jpg"
  }'
```

#### 成功创建响应：
```json
{
  "id": "video_100a89bc2138",
  "object": "video",
  "created_at": 1780000000,
  "status": "queued",
  "model": "grok-imagine-1.0-video",
  "progress": 0,
  "prompt": "Animate the reference image with gentle wind and natural camera motion",
  "seconds": "6",
  "size": "720x1280",
  "quality": "standard"
}
```

### 3.4 查询任务：`GET /v1/videos/{task_id}`
```bash
curl -X GET "https://api.yourdomain.com/v1/videos/video_100a89bc2138" \
  -H "Authorization: Bearer sk-你的Key"
```

#### 成功完成响应：
```json
{
  "id": "video_100a89bc2138",
  "object": "video",
  "status": "completed",
  "model": "grok-imagine-1.0-video",
  "progress": 100,
  "seconds": "6",
  "size": "720x1280",
  "url": "https://api.yourdomain.com/v1/files/video?id=video_100a89bc2138",
  "video_url": "https://api.yourdomain.com/v1/files/video?id=video_100a89bc2138",
  "result_url": "https://api.yourdomain.com/v1/files/video?id=video_100a89bc2138"
}
```

### 3.5 统一创建接口示例 (`POST /v1/video/create`)

本接口同样提供对 `grok-imagine-1.0-video` 的完美支持。

#### 1.0 文生视频：
```bash
curl -X POST "https://api.yourdomain.com/v1/video/create" \
  -H "Authorization: Bearer sk-你的Key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "grok-imagine-1.0-video",
    "prompt": "A cinematic shot of a futuristic city at sunrise, slow camera push-in",
    "aspect_ratio": "16:9",
    "size": "720P",
    "seconds": 10,
    "images": []
  }'
```

#### 1.0 图生视频：
```bash
curl -X POST "https://api.yourdomain.com/v1/video/create" \
  -H "Authorization: Bearer sk-你的Key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "grok-imagine-1.0-video",
    "prompt": "Make the subject walk forward slowly, natural daylight",
    "aspect_ratio": "9:16",
    "size": "720P",
    "seconds": 6,
    "images": [
      "https://example.com/reference.jpg"
    ]
  }'
```

---

## 4. grok-imagine-video-1.5-fast (1.5 快速版详细指南)

快速版大模型提供对生成时间的极致压缩，同时也支持**文生视频**和**图生视频**。

### 4.1 支持的路由接口
* `POST /v1/video/create` —— 统一视频创建 JSON 接口
* `GET /v1/video/query?id={task_id}` —— 统一视频状态查询接口
* `POST /v1/videos` —— OpenAI 兼容创建接口
* `GET /v1/videos/{task_id}` —— OpenAI 兼容状态查询接口

### 4.2 参数限制与说明
* **`seconds` (时长)**: **只支持 `6` 或 `10` 秒**。
* **`aspect_ratio` / `size`**: 支持 `"9:16"`、`"16:9"`、`"1:1"`、`"2:3"`、`"3:2"`。亦支持直接传分辨率（如 `"720x1280"`、`"1280x720"` 等）。
* **清晰度**: 接收 `480P`、`720P`、`480p`、`720p`、`SD`、`HD`。
* **参考图参数**: 支持文生视频 (不传 `images`)，或图生视频（传 `images`、`input_reference`、`input_references` 或 `reference_images`）。

### 4.3 OpenAI 兼容接口示例

#### 快速版文生视频：
```bash
curl -X POST "https://api.yourdomain.com/v1/videos" \
  -H "Authorization: Bearer sk-你的Key" \
  -F "model=grok-imagine-video-1.5-fast" \
  -F "prompt=A cinematic travel video of mountains under golden sunset, smooth drone movement" \
  -F "seconds=10" \
  -F "size=16:9" \
  -F "resolution_name=720p"
```

#### 快速版图生视频：
```bash
curl -X POST "https://api.yourdomain.com/v1/videos" \
  -H "Authorization: Bearer sk-你的Key" \
  -F "model=grok-imagine-video-1.5-fast" \
  -F "prompt=Animate the reference image with gentle wind and natural camera motion" \
  -F "seconds=6" \
  -F "size=9:16" \
  -F "resolution_name=720p" \
  -F "input_reference=https://example.com/reference.jpg"
```

#### 快速版 JSON 图生视频请求：
```bash
curl -X POST "https://api.yourdomain.com/v1/videos" \
  -H "Authorization: Bearer sk-你的Key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "grok-imagine-video-1.5-fast",
    "prompt": "Animate the reference image with gentle wind and natural camera motion",
    "seconds": 6,
    "aspect_ratio": "9:16",
    "resolution": "HD",
    "images": [
      "https://example.com/reference.jpg"
    ]
  }'
```

### 4.4 统一创建接口示例 (`POST /v1/video/create`)
```bash
curl -X POST "https://api.yourdomain.com/v1/video/create" \
  -H "Authorization: Bearer sk-你的Key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "grok-imagine-video-1.5-fast",
    "prompt": "A cinematic shot of a futuristic city at sunrise, slow camera push-in",
    "aspect_ratio": "16:9",
    "size": "720P",
    "seconds": 10,
    "images": []
  }'
```

---

## 5. 请求体参数兼容性说明

为支持不同开发语言与中继平台（如 NewAPI、OpenAI 等）的无缝迁移，本网关在解析创建请求时，对各字段进行了高度模糊匹配兼容：

### 5.1 JSON 请求参数自动映射关系

当您通过 JSON 传参时，以下字段属于别名关系，系统会自动识别并提取：

| 标准语义名称 | 可接收解析的参数字段名 (系统会自动按顺序探测获取) |
| :--- | :--- |
| **模型** | `model` |
| **提示词** | `prompt` |
| **时长 (秒)** | `seconds`, `duration`, `video_length`, `video_config.video_length`, `video_config.duration`, `video_config.seconds` |
| **画面画幅** | `aspect_ratio`, `video_config.aspect_ratio` |
| **像素大小** | `size`, `video_config.size` |
| **清晰度等级** | `resolution`, `resolution_name`, `video_config.resolution`, `video_config.resolution_name` |
| **输入参考图** | `input_reference`, `input_references`, `reference_images`, `images` |

### 5.2 Multipart 表单请求参数说明 (`multipart/form-data`)

本网关支持标准 HTTP 表单解析，支持参数如下：

| 表单字段 (Key) | 数据类型 | 字段含义说明 |
| :--- | :--- | :--- |
| **`model`** | string | 调用的模型名称 (如 `grok-imagine-video`) |
| **`prompt`** | string | 视频提示词内容 |
| **`seconds`** | string/int | 视频时长秒数 |
| **`size`** | string | 画幅比或输出分辨率 (例如 `9:16`, `1280x720`) |
| **`aspect_ratio`** | string | 部分旧版客户端兼容画幅比例传值 |
| **`resolution_name`** | string | 清晰度等级名称：`480p` 或 `720p` |
| **`preset`** | string | 运动预设，可选值：`normal`, `fun`, `spicy`, `custom` |
| **`input_reference`** | string | 输入参考图的**公网图片 URL 字符串** |
| **`input_reference[]`**| file binary | 支持直接**表单上传本地图片文件二进制流** |

---

## 6. 错误处理与调试建议

在视频创建与轮询期间，如果发生失败，接口或任务状态将返回具体的错误代码。以下是常见错误码及排查建议：

| 错误代码/内容 | 发生原因 | 排查与调整建议 |
| :--- | :--- | :--- |
| **`seconds must be one of ...`** | 提交的时长不支持。例如 1.0 或 1.5-fast 传入了 `12` 秒。 | 将时长改为该模型对应的可用值（1.0 系列与 1.5-fast 只支持 `6` 或 `10`；仅 1.5-preview 支持 `1` 到 `15`）。 |
| **`requires an input image`** | 调用 `grok-imagine-video-1.5-preview` 时未在参数中提供参考图片。 | 补充 `images` 数组或 `input_reference` 指向的公网图片 URL。 |
| **`images must contain exactly one image URL`** | 对 1.5-preview 模型传入了空图片，或者传入了多张图片。 | 1.5-preview 模型必须且**只能**接收 1 张输入参考图，检查并清空多余项。 |
| **`Image URL could not be fetched`** | 上游系统拉取或下载您提供的参考图链接失败。 | 确认您提供的参考图 URL 能够在公网直接免登录访问，并确保响应头是正确的 `Content-Type: image/jpeg` 或 `image/png` |
| **`Asset upload returned 403`** | 图片上传被上游平台拦截，或图片可能触发了某些内容合规拦截规则。 | 更换图片链接、重新压缩图片或对敏感画面进行适当裁剪后重试。 |
| **`No available accounts`** | 当前系统池中暂无可用账号或者被暂时限流。 | 稍等几分钟后重新提交，或联系管理员确认账号池存量。 |

---

## 7. 多语言调用实现示例

### 7.1 Python 轮询请求完整示例

```python
import time
import requests

# 配置您的网关信息与密钥
BASE_URL = "https://api.yourdomain.com"
API_KEY = "sk-你的Key"

headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
}

# 提交 1.5-fast 视频生成请求 (支持文生视频，不需要参考图)
payload = {
    "model": "grok-imagine-video-1.5-fast",
    "prompt": "A beautiful cinematic flythrough of a neon city at night, 4k, hyper-realistic, no text",
    "aspect_ratio": "16:9",
    "size": "720P",
    "seconds": 10,
    "images": [],
}

print("正在提交视频任务...")
create_resp = requests.post(
    f"{BASE_URL}/v1/video/create",
    headers=headers,
    json=payload,
    timeout=60,
)
create_resp.raise_for_status()
task = create_resp.json()
video_id = task["id"]
print(f"任务提交成功，任务 ID: {video_id}，开始轮询状态...")

# 轮询状态
while True:
    query_resp = requests.get(
        f"{BASE_URL}/v1/video/query",
        headers={"Authorization": f"Bearer {API_KEY}"},
        params={"id": video_id},
        timeout=60,
    )
    query_resp.raise_for_status()
    data = query_resp.json()
    status = data.get("status")

    if status in ("completed", "success"):
        # 成功，获取视频下载直链
        video_url = data.get("video_url") or data.get("url") or data.get("result_url")
        print(f"\n🎉 视频生成成功！下载直链 URL:\n{video_url}")
        break

    if status == "failed":
        print(f"\n❌ 视频生成失败，原因: {data.get('error') or data.get('fail_reason')}")
        break

    print(f"当前状态: [{status}] | 生成进度: {data.get('progress')}%")
    time.sleep(5)
```

### 7.2 Node.js (ES Module) 轮询请求完整示例

```javascript
import fetch from 'node-fetch';

const BASE_URL = 'https://api.yourdomain.com';
const API_KEY = 'sk-你的Key';

async function generateVideo() {
  const payload = {
    model: 'grok-imagine-video-1.5-preview',
    prompt: 'Animate this character running under moonlight, cinematic rendering',
    aspect_ratio: '9:16',
    size: '720P',
    seconds: 10,
    images: ['https://example.com/character.jpg'] // 1.5-preview 必须传图
  };

  console.log('正在创建视频生成任务...');
  const res = await fetch(`${BASE_URL}/v1/video/create`, {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${API_KEY}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(payload)
  });

  const task = await res.json();
  if (!res.ok || !task.id) {
    throw new Error(`创建任务失败: ${JSON.stringify(task)}`);
  }

  const taskId = task.id;
  console.log(`任务创建成功，ID: ${taskId}。开始轮询状态...`);

  const poll = setInterval(async () => {
    try {
      const qRes = await fetch(`${BASE_URL}/v1/video/query?id=${taskId}`, {
        headers: { 'Authorization': `Bearer ${API_KEY}` }
      });
      const data = await qRes.json();
      const status = data.status;

      if (status === 'success' || status === 'completed') {
        const videoUrl = data.video_url || data.url || data.result_url;
        console.log(`\n🎉 视频生成成功！下载直链: ${videoUrl}`);
        clearInterval(poll);
      } else if (status === 'failed') {
        console.log(`\n❌ 视频生成失败，原因: ${data.error}`);
        clearInterval(poll);
      } else {
        console.log(`当前状态: [${status}] | 生成进度: ${data.progress}%`);
      }
    } catch (err) {
      console.error('轮询出错:', err);
      clearInterval(poll);
    }
  }, 5000);
}

generateVideo().catch(console.error);
```

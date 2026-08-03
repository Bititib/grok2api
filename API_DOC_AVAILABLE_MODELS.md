# `grokai.zhubo.asia` API 接口文档

本文档说明平台提供的全套模型与 API 调用方式。视频生成采用**异步任务模式**：提交任务后获得 `task_id`，再轮询获取最终生成结果。

---

## 1. 基础信息

| 项目 | 说明 |
|---|---|
| **Base URL** | `https://grokai.zhubo.asia` |
| **鉴权方式** | `Authorization: Bearer YOUR_API_KEY`（HTTP 请求头中携带） |
| **请求格式** | `application/json`（推荐）或 `multipart/form-data` |

---

## 2. 模型清单与计费说明

### 2.1 视频生成模型

| 模型名称 | 渲染画质 | 支持比例 | 允许时长 | 参考媒体支持 | 计费单价 | 模型说明 |
|---|---|---|---|---|---|---|
| **`omni-flash`** | `720p` / `1080p` | `16:9` / `9:16` | 自定义 | ✅ 支持多张参考图 | **0.12 元 / 秒 (720p)** | Omni 动态计费视频 |
| **`omni-flash-vref`** | `720p` / `1080p` | `16:9` / `9:16` | 自定义 | ✅ 支持视频参考控制 | **0.22 元 / 秒 (720p)** | Omni 视频参考控制生成 |
| **`sd2-c7`** | `720p` | `16:9` / `9:16` / `1:1` / `21:9` / `3:4` / `4:3` | `5`–`15` 秒 | ✅ 最多 9 张参考图 | **1.50 元 / 次** | Seedance 2.0 9图参考生成 |
| **`sd2-mini`** | `720p` | `16:9` / `9:16` / `1:1` / `21:9` / `3:4` / `4:3` | `5`–`15` 秒 | ✅ 图(9) / 视(3) / 音(3) | **2.00 元 / 次** | Seedance Mini 720p 多模态视频生成 |
| **`seedance-2.0-720p`** | `720p` | `16:9` / `9:16` / `1:1` / `21:9` / `3:4` / `4:3` | `5`–`15` 秒 | ✅ 图(9) / 视(3) / 音(3) / 真人面部 | **4.00 元 / 次** | Seedance 2.0 满血版（人脸参考+合规素材） |
| **`seedance-2.0-fast-720p`** | `720p` | `16:9` / `9:16` / `1:1` / `21:9` / `3:4` / `4:3` | `5`–`15` 秒 | ✅ 图(9) / 视(3) / 音(3) | **3.00 元 / 次** | Seedance 2.0 高速版视频生成 |
| **`sora-v3-933-pro`** | `720p` | `16:9` / `9:16` / `4:3` / `3:4` / `1:1` / `21:9` | `5`–`15` 秒 | ✅ 图(9) / 视(3) / 音(3) | **3.00 元 / 次** | 933 真人视频生成（支持图片/视频/音频多模态参考） |
| **`tejiasd2`** | `720p` | `16:9` / `9:16` / `4:3` / `3:4` / `1:1` / `21:9` | `5`–`15` 秒 | ✅ 图(9) / 视(3) / 音(3) | **3.00 元 / 次** | 特价真人视频生成（同 sora-v3-933-pro 渠道） |
| **`ld-sdas-h3-501-2k`** | `2k` | `1:1` / `3:4` / `4:3` / `9:16` / `16:9` | `5`–`15` 秒 | ✅ 图(5) / 视(0) / 音(1) / 真人面部 | **2.50 元 / 次** | 海螺h3 高清视频生成（支持真人/按次计费） |
| **`sd2.0-480p`** | `480p` | `16:9` / `9:16` / `1:1` / `4:3` / `3:4` / `21:9` | `4`–`15` 秒 | ✅ 图(9) / 视(3) / 音(3) / 真人面部 | **0.30 元 / 秒** | Seedance 2.0 480p 满血版（按秒计费） |
| **`sd2.0-fast-480p`** | `480p` | `16:9` / `9:16` / `1:1` / `4:3` / `3:4` / `21:9` | `4`–`15` 秒 | ✅ 图(9) / 视(3) / 音(3) / 真人面部 | **0.18 元 / 秒** | Seedance 2.0 480p 快速版（按秒计费） |

---

### 2.2 工具与功能模型

| 模型名称 | 应用类型 | 计费单价 | 功能说明 |
|---|---|---|---|
| **`omni-watermark-remover`** | 去水印 | **0.10 元 / 次** | AI 智能视频/图片去水印 |
| **`omni-moderation-latest`** | 内容审核 | **0.02 元 / 次** | 文本/图像多模态安全合规审核 |

### 2.3 图像生成模型

| 模型名称 | 应用类型 | 计费单价 | 功能说明 |
|---|---|---|---|
| **`gpt-image-2`** | 图像生成/重绘 | **0.12 元 / 次** | Pidoi 渠道高品质图片生成与重绘接口 |

---

## 3. 接口调用指南

### 3.1 统一创建视频任务接口：`POST /v1/video/create`

推荐客户端统一使用该 JSON 接口进行任务提交。

* **请求 Headers**：
  ```http
  Authorization: Bearer YOUR_API_KEY
  Content-Type: application/json
  ```

* **请求参数 (JSON Body)**：

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `model` | string | 是 | - | 模型名称（如 `sora-v3-933-pro`、`seedance-2.0-fast-720p`） |
| `prompt` | string | 是 | - | 视频生成提示词 |
| `aspect_ratio` | string | 否 | `"16:9"` | 视频比例：`"16:9"` 或 `"9:16"` |
| `seconds` / `duration` | integer / string | 否 | `6` | 视频时长（秒） |
| `images` | array[string] | 否 | `[]` | 参考图片 HTTP/HTTPS URL 列表 |

#### cURL 示例 1：文生视频 (Text to Video)
```bash
curl -X POST "https://grokai.zhubo.asia/v1/video/create" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "seedance-2.0-fast-720p",
    "prompt": "A beautiful butterfly landing on a colorful flower, cinematic 4k",
    "aspect_ratio": "16:9",
    "seconds": 6
  }'
```

#### cURL 示例 2：多图图生视频 (Image to Video)
```bash
curl -X POST "https://grokai.zhubo.asia/v1/video/create" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "omni-flash",
    "prompt": "Create a smooth cinematic transition between these two frames",
    "aspect_ratio": "16:9",
    "duration": 4,
    "images": [
      "https://example.com/start_frame.jpg",
      "https://example.com/end_frame.jpg"
    ]
  }'
```

* **任务提交成功响应 (HTTP 200)**：
```json
{
  "id": "task_auzaji6FWDFtnrogiJvyly6uPAD0SsAH",
  "task_id": "task_auzaji6FWDFtnrogiJvyly6uPAD0SsAH",
  "object": "video",
  "model": "seedance-2.0-fast-720p",
  "status": "queued",
  "progress": 0,
  "created_at": 1785311571
}
```

---

### 3.2 统一查询视频任务接口：`GET /v1/video/query`

提交任务后，建议客户端每隔 **5 - 8 秒** 查询一次任务 status。

* **请求方式**：
```bash
curl -X GET "https://grokai.zhubo.asia/v1/video/query?id=task_auzaji6FWDFtnrogiJvyly6uPAD0SsAH" \
  -H "Authorization: Bearer YOUR_API_KEY"
```

* **渲染完成响应 (completed)**：
```json
{
  "id": "task_auzaji6FWDFtnrogiJvyly6uPAD0SsAH",
  "status": "completed",
  "progress": 100,
  "model": "seedance-2.0-fast-720p",
  "video_url": "https://grokai.zhubo.asia/v1/files/video?id=e38b5247-e327-4024-8ee5-3462d5375b48"
}
```
*客户端直接使用响应中的 `video_url` 播放或下载 MP4 视频。*

---

### 3.3 OpenAI 兼容表单上传接口：`POST /v1/videos`

如果需要直接上传本地图片文件进行图生视频，可以使用表单提交接口：

```bash
curl -X POST "https://grokai.zhubo.asia/v1/videos" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -F "model=sora-v3-933-pro" \
  -F "prompt=Animate this uploaded photo" \
  -F "seconds=15" \
  -F "input_reference[]=@/path/to/local_image.jpg"
```

---

### 3.4 Seedance 2.0 多模态与人脸参考接口：`POST /v1/videos`

Seedance 2.0 模型（`sd2-c7`、`sd2-mini`、`seedance-2.0-720p`、`seedance-2.0-fast-720p`）支持多张图片、视频与音频参考联动，提示词可通过 `@ImageN`、`@VideoN`、`@AudioN` 引用素材。

> **注意**：`sora-v3-933-pro` / `tejiasd2` 模型也通过此接口调用，参数格式见下方 3.5 节。

| 参数 | 类型 | 说明 |
|---|---|---|
| `model` | string | `sd2-c7`（1.5元/次）、`sd2-mini`（2.0元/次）、`seedance-2.0-720p`（4.0元/次）、`seedance-2.0-fast-720p`（3.0元/次） |
| `prompt` | string | 提示词，引用素材时插入 `@Image1`、`@Video1`、`@Audio1` 等占位符 |
| `duration` | integer | 视频时长（秒），范围 `5`–`15`，默认 `8` |
| `aspect_ratio` | string | 画面比例：`16:9`（默认）、`9:16`、`1:1`、`21:9`、`3:4` / `4:3` |
| `image_refs` | array[string] | 图片参考 URL 列表，最多 **9** 张（支持真人面部或身体照片） |
| `video_refs` | array[string] | 视频参考 URL 列表，最多 **3** 条（用于动作、镜头参考） |
| `audio_refs` | array[string] | 音频参考 URL 列表，最多 **3** 条（用于配音、音色参考） |
| `compliance_enabled` | boolean | 是否开启合规素材风格（默认 `false`） |
| `compliance_mode` | string | 合规素材风格：`colored-pencil`（彩铅）、`watercolor`（水彩）、`fishnet`（渔网）、`grid`（眼部遮罩） |

#### cURL 示例：Seedance 2.0 多模态人脸与音视频联动调用

```bash
curl -X POST "https://grokai.zhubo.asia/v1/videos" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "seedance-2.0-720p",
    "prompt": "@Image1 是张三，张三使用 @Audio1。@Image2 是小红，小红参考 @Video1 的动作。两人面向镜头分别说：欢迎来到门的世界。",
    "duration": 15,
    "aspect_ratio": "16:9",
    "image_refs": [
      "https://example.com/image1.png",
      "https://example.com/image2.jpg"
    ],
    "audio_refs": [
      "https://example.com/audio1.wav"
    ],
    "video_refs": [
      "https://example.com/video1.mp4"
    ],
    "compliance_enabled": true,
    "compliance_mode": "colored-pencil"
  }'
```

---

### 3.5 933 真人视频模型接口：`POST /v1/video/create`

模型 `sora-v3-933-pro` 和 `tejiasd2` 支持真人面部保持、图片/视频/音频多模态参考。系统会自动补全必填参数 `resolution = "720p"`。

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `model` | string | 是 | `sora-v3-933-pro` 或 `tejiasd2` |
| `prompt` | string | 是 | 视频描述提示词 |
| `aspect_ratio` | string | 是 | `16:9` / `9:16` / `4:3` / `3:4` / `1:1` / `21:9` |
| `seconds` | string / integer | 否 | 视频时长（秒），默认 `"15"` |
| `image_url` | string | 否 | 主参考图 URL |
| `reference_image_urls` | array | 否 | 额外参考图，与 `image_url` 合计最多 9 张 |
| `reference_videos` | array | 否 | 参考视频 URL 列表，最多 3 个 |
| `audio_url` / `audio_urls` | string / array | 否 | 参考音频 URL |

#### cURL 示例：933 真人文生视频
```bash
curl -X POST "https://grokai.zhubo.asia/v1/video/create" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "sora-v3-933-pro",
    "prompt": "雨夜霓虹街道，镜头缓慢推进，电影感光影",
    "aspect_ratio": "16:9",
    "seconds": "15"
  }'
```

#### cURL 示例：933 真人图生视频（图片+音频参考）
```bash
curl -X POST "https://grokai.zhubo.asia/v1/video/create" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "sora-v3-933-pro",
    "prompt": "保持人物外貌一致，并参考音频节奏生成对应的视频画面",
    "image_url": "https://example.com/input-image.jpg",
    "audio_url": "https://example.com/reference-audio.mp3",
    "aspect_ratio": "16:9",
    "seconds": "15"
  }'
```

### 3.6 图像生成接口：`POST /v1/images/generations`

调用该接口向 Pidoi 渠道请求生成高品质图像。支持的参数如下：

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `model` | string | 是 | 使用 `gpt-image-2` |
| `prompt` | string | 是 | 要生成图像的详细描述词 |
| `size` | string | 否 | 图像尺寸，默认 `"1024x1024"` |
| `quality` | string | 否 | 图像质量，如 `"high"`、`"standard"` |
| `n` | integer | 否 | 生成张数，目前固定为 `1` |
| `response_format` | string | 否 | 返回格式类型，通常支持 `"url"` 或是 `"b64_json"` |

#### cURL 示例：文生图
```bash
curl -X POST "https://grokai.zhubo.asia/v1/images/generations" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-image-2",
    "prompt": "一个极简主义的现代书桌，上面放着一台笔记本电脑和咖啡，柔和的晨光",
    "size": "1024x1024"
  }'
```

---

## 4. Python 生产级代码示例

```python
import time
import requests

BASE_URL = "https://grokai.zhubo.asia"
API_KEY = "sk-xxxxxxxxxxxxxxxxxxxxxxxx"  # 替换为您的密钥

headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
}

def generate_video(model_name: str, prompt: str, aspect_ratio: str = "16:9", images: list = None):
    # 1. 提交视频生成任务
    payload = {
        "model": model_name,
        "prompt": prompt,
        "aspect_ratio": aspect_ratio,
        "seconds": 6,
    }
    if images:
        payload["images"] = images

    print(f"正在提交任务 (模型: {model_name})...")
    response = requests.post(f"{BASE_URL}/v1/video/create", json=payload, headers=headers, timeout=30)
    response.raise_for_status()

    result = response.json()
    task_id = result.get("task_id") or result.get("id")
    print(f"任务提交成功！Task ID: {task_id}")

    # 2. 轮询视频生成进度
    start_time = time.time()
    while True:
        time.sleep(5)
        query_resp = requests.get(
            f"{BASE_URL}/v1/video/query",
            params={"id": task_id},
            headers={"Authorization": f"Bearer {API_KEY}"},
            timeout=15,
        )
        query_resp.raise_for_status()
        data = query_resp.json()
        
        status = data.get("status")
        progress = data.get("progress", 0)
        elapsed = int(time.time() - start_time)
        print(f"[{elapsed}s] 状态: {status:<12} | 进度: {progress}%")
        
        if status == "completed":
            video_url = data.get("video_url") or data.get("url")
            print(f"\n🎉 视频生成完成！播放/下载链接:\n{video_url}")
            return video_url
        elif status in ("failed", "error"):
            error_msg = data.get("error")
            print(f"\n❌ 视频生成失败: {error_msg}")
            raise RuntimeError(f"Video generation failed: {error_msg}")

# 使用示例：
if __name__ == "__main__":
    generate_video(
        model_name="sora-v3-933-pro",
        prompt="A butterfly landing on a colorful flower, cinematic 4k"
    )
```

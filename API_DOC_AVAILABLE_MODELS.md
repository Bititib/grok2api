# `grokai.zhubo.asia` 全渠道 API 接口文档 (完整模型与渠道版)

本文档说明目前系统中配置的**全部三个中转渠道（PIDOI 渠道、DSZ 渠道、Omni 渠道）**的模型清单与 API 调用方式。视频生成采用**异步任务模式**：提交任务后获得 `task_id`，再轮询获取最终生成结果。

---

## 1. 基础信息

| 项目 | 说明 |
|---|---|
| **Base URL** | `https://grokai.zhubo.asia` |
| **鉴权方式** | `Authorization: Bearer YOUR_API_KEY`（HTTP 请求头中携带） |
| **请求格式** | `application/json`（推荐）或 `multipart/form-data` |

---

## 2. 三大渠道与完整模型清单

### 2.1 PIDOI 视频渠道 (`https://pidoi.com`)

| 模型名称 | 渲染画质 | 支持比例 | 允许时长 | 多参考图/视频支持 | 扣费单价 | 说明 |
|---|---|---|---|---|---|---|
| **`veo31-fast`** | `720p` / `1080p` | `16:9` / `9:16` | `4` / `6` / `8` 秒 | ✅ 最多 2 张 (首尾帧) | **$0.60 美元 / 次** | Veo31 高清视频生成 |
| **`gemini-omni-flash`** | `720p` / `1080p` | `16:9` / `9:16` | `4` / `6` / `8` / `10` 秒 | ✅ 最多 5 图 / 1 视频 | **$0.85 美元 / 次** | 强多模态风格与镜头追踪 |
| **`sora2`** | `720p` | `16:9` / `9:16` | `4` / `8` / `12` 秒 | ✅ 最多 1 张图 | **按次扣费** | Sora2 基础视频生成 |

---

### 2.2 DSZ Grok 视频渠道 (`https://new.dszyym.com`)

| 模型名称 | 渲染画质 | 支持比例 | 允许时长 | 多参考图支持 | 扣费单价 | 说明 |
|---|---|---|---|---|---|---|
| **`grok-imagine-1.0-video`** | `720p` | `16:9` / `9:16` | `6` 秒 | ✅ 支持多图 | **$0.40 美元 / 次** | Grok 经典版中转模型 |
| **`grok-imagine-video-1.5-fast`** | `720p` | `16:9` / `9:16` | `6` 秒 | ✅ 支持多图 | **$0.40 美元 / 次** | Grok 快速版中转模型 |
| **`grok-imagine-video-1.5-preview`** | `720p` | `16:9` / `9:16` | `6` 秒 | ⚠️ 仅限 1 张图 | **$0.50 美元 / 次** | 1.5 预览版图生视频专有模型 |

---

### 2.3 Omni 专有工具渠道 (`https://llm.zerofall.top`)

| 模型名称 | 应用类型 | 计费模式 | 扣费单价 | 说明 |
|---|---|---|---|---|
| **`omni-flash`** | 视频生成 | 按秒计费 | **$0.12 美元 / 秒 (720p)** | Omni 闪电版视频 |
| **`omni-flash-vref`** | 视频参考生成 | 按秒计费 | **$0.22 美元 / 秒 (720p)** | 带视频参考控制的生成 |
| **`omni-watermark-remover`** | 工具 / 去水印 | 按次计费 | **$0.10 美元 / 次** | 智能去水印工具 API |
| **`omni-moderation-latest`** | 内容审核 | 按次计费 | **$0.02 美元 / 次** | 文本/图像内容安全审核 |

---

## 3. 接口调用指南

### 3.1 统一创建视频任务接口：`POST /v1/video/create`

* **请求 Headers**：
  ```http
  Authorization: Bearer YOUR_API_KEY
  Content-Type: application/json
  ```

* **请求参数 (JSON Body)**：

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `model` | string | 是 | - | 模型名称（如 `grok-imagine-1.0-video`、`veo31-fast`、`omni-flash`） |
| `prompt` | string | 是 | - | 视频生成提示词 |
| `aspect_ratio` | string | 否 | `"16:9"` | 视频比例：`"16:9"` 或 `"9:16"` |
| `seconds` / `duration` | integer / string | 否 | `6` | 视频时长（秒） |
| `images` | array[string] | 否 | `[]` | 参考图片 HTTP/HTTPS URL 列表 |

#### cURL 示例 (生成视频)
```bash
curl -X POST "https://grokai.zhubo.asia/v1/video/create" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "grok-imagine-1.0-video",
    "prompt": "A beautiful butterfly landing on a colorful flower, cinematic 4k",
    "aspect_ratio": "16:9",
    "seconds": 6
  }'
```

* **任务提交成功响应 (HTTP 200)**：
```json
{
  "id": "dszyym_grok:task_auzaji6FWDFtnrogiJvyly6uPAD0SsAH",
  "task_id": "dszyym_grok:task_auzaji6FWDFtnrogiJvyly6uPAD0SsAH",
  "object": "video",
  "model": "grok-imagine-1.0-video",
  "status": "queued",
  "progress": 0,
  "created_at": 1785311571
}
```

---

### 3.2 统一查询视频任务接口：`GET /v1/video/query`

提交任务后，建议客户端每隔 **5 - 8 秒** 查询一次任务状态。

* **请求方式**：
```bash
curl -X GET "https://grokai.zhubo.asia/v1/video/query?id=dszyym_grok:task_auzaji6FWDFtnrogiJvyly6uPAD0SsAH" \
  -H "Authorization: Bearer YOUR_API_KEY"
```

* **渲染完成响应 (completed)**：
```json
{
  "id": "dszyym_grok:task_auzaji6FWDFtnrogiJvyly6uPAD0SsAH",
  "status": "completed",
  "progress": 100,
  "model": "grok-imagine-1.0-video",
  "video_url": "https://grokai.zhubo.asia/v1/files/video?id=e38b5247-e327-4024-8ee5-3462d5375b48"
}
```

---

### 3.3 OpenAI 兼容表单上传接口：`POST /v1/videos`

如果需要直接上传本地图片文件进行图生视频，可以使用表单提交接口：

```bash
curl -X POST "https://grokai.zhubo.asia/v1/videos" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -F "model=grok-imagine-1.0-video" \
  -F "prompt=Animate this uploaded photo" \
  -F "seconds=6" \
  -F "input_reference[]=@/path/to/local_image.jpg"
```

---

## 4. Python 生产级代码示例

```python
import time
import requests

BASE_URL = "https://grokai.zhubo.asia"
API_KEY = "sk-xxxxxxxxxxxxxxxxxxxxxxxx"

headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
}

def generate_video(model_name: str, prompt: str, aspect_ratio: str = "16:9", images: list = None):
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

if __name__ == "__main__":
    generate_video(
        model_name="grok-imagine-1.0-video",
        prompt="A butterfly landing on a colorful flower, cinematic 4k"
    )
```

# zhuboApi 视频生成接口文档

> **Base URL**: `https://grokai.zhubo.asia`  
> **认证方式**: `Authorization: Bearer <API_KEY>`

---

## 概述

视频生成接口采用**异步模式**，调用流程分三步：

```
① 提交任务 → ② 轮询状态 → ③ 获取视频
   POST           GET            GET
  /v1/videos    /v1/videos/{id}  /v1/files/video?id={id}
```

---

## 1. 创建视频任务

```
POST /v1/videos
Content-Type: multipart/form-data
Authorization: Bearer <API_KEY>
```

### 请求参数

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `model` | string | ✅ | — | 视频模型名（见下方可用模型） |
| `prompt` | string | ✅ | — | 视频内容描述 |
| `seconds` | int | — | `6` | 时长，可选值: `6` `10` `12` `16` `20` `30` |
| `size` | string | — | `720x1280` | 画幅尺寸（见下方可选值） |
| `resolution_name` | string | — | `720p` | 分辨率: `480p` 或 `720p` |
| `preset` | string | — | — | 风格预设: `fun` `normal` `spicy` `custom` |
| `input_reference[]` | file | — | — | 参考图片文件（最多 5 张） |
| `input_reference_url[]` | string | — | — | 参考图片 URL（最多 5 个） |

### 可用模型

| 模型名 | 说明 | 推荐 |
|--------|------|------|
| `grok-imagine-video` | 标准视频生成 | ⭐ 推荐 |
| `grok-4.3-video` | Grok 4.3 视频 | |
| `grok-4.3-video-heavy` | Grok 4.3 视频（Heavy 级）(不可用) | |

### 画幅尺寸

| size | 说明 |
|------|------|
| `720x1280` | 竖屏 9:16（默认） |
| `1280x720` | 横屏 16:9 |
| `1024x1024` | 正方形 1:1 |
| `1024x1792` | 竖屏 9:16 高分辨率 |
| `1792x1024` | 横屏 16:9 高分辨率 |

### 计费

| 分辨率 | 单价 | 6 秒 | 10 秒 | 20 秒 | 30 秒 |
|--------|------|------|-------|-------|-------|
| 480p | $0.02/秒 | $0.12 | $0.20 | $0.40 | $0.60 |
| 720p | $0.03/秒 | $0.18 | $0.30 | $0.60 | $0.90 |

> 生成失败不扣费。

---

## 2. 调用示例

### 2.1 基础调用（纯文字）

**curl:**

```bash
curl -X POST https://grokai.zhubo.asia/v1/videos \
  -H "Authorization: Bearer sk-你的Key" \
  -F "model=grok-imagine-video" \
  -F "prompt=一只猫在月球上跳舞，科幻风格，电影级画质" \
  -F "seconds=6" \
  -F "size=1280x720"
```

**Python:**

```python
import requests

resp = requests.post("https://grokai.zhubo.asia/v1/videos",
    headers={"Authorization": "Bearer sk-你的Key"},
    data={
        "model": "grok-imagine-video",
        "prompt": "一只猫在月球上跳舞，科幻风格，电影级画质",
        "seconds": 6,
        "size": "1280x720",
    }
)
print(resp.json())
# {"id": "video_xxx", "status": "queued", ...}
```

**响应:**

```json
{
  "id": "video_61be39094ee24240b27a09c673beb068",
  "object": "video",
  "created_at": 1779357896,
  "status": "queued",
  "model": "grok-imagine-video",
  "progress": 0,
  "prompt": "一只猫在月球上跳舞，科幻风格，电影级画质",
  "seconds": "6",
  "size": "1280x720",
  "quality": "standard"
}
```

### 2.2 带参考图（本地文件上传）

系统会提取参考图中的人物特征，生成的视频角色会还原参考图中的人物外貌。

**curl:**

```bash
curl -X POST https://grokai.zhubo.asia/v1/videos \
  -H "Authorization: Bearer sk-你的Key" \
  -F "model=grok-imagine-video" \
  -F "prompt=两个角色在街头激烈格斗，动作片风格" \
  -F "seconds=6" \
  -F "size=1280x720" \
  -F "input_reference[]=@./character_a.jpg" \
  -F "input_reference[]=@./character_b.jpg"
```

**Python:**

```python
import requests

files = [
    ("input_reference[]", ("角色A.jpg", open("character_a.jpg", "rb"), "image/jpeg")),
    ("input_reference[]", ("角色B.jpg", open("character_b.jpg", "rb"), "image/jpeg")),
]

resp = requests.post("https://grokai.zhubo.asia/v1/videos",
    headers={"Authorization": "Bearer sk-你的Key"},
    data={
        "model": "grok-imagine-video",
        "prompt": "两个角色在街头激烈格斗，动作片风格",
        "seconds": 6,
        "size": "1280x720",
    },
    files=files,
)
print(resp.json())
```

### 2.3 带参考图（URL 方式）

如果图片已在线上，可以直接传 URL，无需下载再上传。

**curl:**

```bash
curl -X POST https://grokai.zhubo.asia/v1/videos \
  -H "Authorization: Bearer sk-你的Key" \
  -F "model=grok-imagine-video" \
  -F "prompt=角色在赛道上飙车，速度感十足" \
  -F "seconds=10" \
  -F "size=1280x720" \
  -F "input_reference_url[]=https://example.com/driver1.jpg" \
  -F "input_reference_url[]=https://example.com/driver2.jpg"
```

### 2.4 长视频（自动分段拼接）

超过 10 秒的视频会自动分段生成并拼接，无需额外处理。

```bash
curl -X POST https://grokai.zhubo.asia/v1/videos \
  -H "Authorization: Bearer sk-你的Key" \
  -F "model=grok-imagine-video" \
  -F "prompt=一段日落延时摄影，从黄昏过渡到星空" \
  -F "seconds=30" \
  -F "size=1280x720" \
  -F "resolution_name=480p"
```

---

## 3. 轮询视频状态

```
GET /v1/videos/{video_id}
Authorization: Bearer <API_KEY>
```

提交任务后，每隔 **5 秒**轮询一次状态，直到 `status` 变为 `completed` 或 `failed`。

```bash
curl https://grokai.zhubo.asia/v1/videos/video_61be39094ee24240b27a09c673beb068 \
  -H "Authorization: Bearer sk-你的Key"
```

### 状态说明

| status | 含义 | 说明 |
|--------|------|------|
| `queued` | 排队中 | 任务已提交，等待处理 |
| `processing` | 生成中 | 正在生成，`progress` 字段显示百分比 |
| `completed` | 已完成 | 视频已生成，`url` 字段包含下载地址 |
| `failed` | 失败 | `error.message` 字段包含原因 |

### 生成中响应

```json
{
  "id": "video_61be39094ee24240b27a09c673beb068",
  "object": "video",
  "status": "processing",
  "progress": 65,
  "model": "grok-imagine-video",
  "prompt": "...",
  "seconds": "6",
  "size": "1280x720",
  "quality": "standard"
}
```

### 完成响应

```json
{
  "id": "video_61be39094ee24240b27a09c673beb068",
  "object": "video",
  "status": "completed",
  "progress": 100,
  "completed_at": 1779357919,
  "url": "https://grokai.zhubo.asia/v1/files/video?id=video_61be39094ee24240b27a09c673beb068",
  "model": "grok-imagine-video",
  "prompt": "...",
  "seconds": "6",
  "size": "1280x720",
  "quality": "standard"
}
```

### 失败响应

```json
{
  "id": "video_xxx",
  "object": "video",
  "status": "failed",
  "error": {
    "message": "Video generation was blocked by content moderation"
  }
}
```

---

## 4. 下载视频

### 方式一（推荐）

```
GET /v1/files/video?id={video_id}
```

**无需认证**，返回 `video/mp4` 文件流，可直接在浏览器播放或用程序下载。

```bash
# 浏览器直接打开
https://grokai.zhubo.asia/v1/files/video?id=video_61be39094ee24240b27a09c673beb068

# curl 下载
curl -o output.mp4 "https://grokai.zhubo.asia/v1/files/video?id=video_61be39094ee24240b27a09c673beb068"
```

### 方式二

```
GET /v1/videos/{video_id}/content
```

功能相同，无需认证。

---

## 5. 完整调用流程

### Python 完整示例

```python
import time
import requests

API_KEY = "sk-你的Key"
BASE = "https://grokai.zhubo.asia"
HEADERS = {"Authorization": f"Bearer {API_KEY}"}

# ━━━ Step 1: 创建视频任务 ━━━
resp = requests.post(f"{BASE}/v1/videos", headers=HEADERS, data={
    "model": "grok-imagine-video",
    "prompt": "一只猫在月球上跳舞，科幻风格",
    "seconds": 6,
    "size": "1280x720",
})
job = resp.json()
video_id = job["id"]
print(f"✅ 任务已创建: {video_id}")

# ━━━ Step 2: 轮询等待完成 ━━━
while True:
    r = requests.get(f"{BASE}/v1/videos/{video_id}", headers=HEADERS).json()
    status = r["status"]
    progress = r.get("progress", 0)
    print(f"   状态: {status} | 进度: {progress}%")

    if status == "completed":
        video_url = r["url"]
        print(f"✅ 视频生成完成!")
        print(f"   下载地址: {video_url}")
        break
    elif status == "failed":
        print(f"❌ 生成失败: {r.get('error', {}).get('message', '未知错误')}")
        break

    time.sleep(5)

# ━━━ Step 3: 下载视频文件 ━━━
if status == "completed":
    video_data = requests.get(video_url).content
    with open("output.mp4", "wb") as f:
        f.write(video_data)
    print(f"✅ 已保存为 output.mp4 ({len(video_data) / 1024:.0f} KB)")
```

### Python 带参考图完整示例

```python
import time
import requests

API_KEY = "sk-你的Key"
BASE = "https://grokai.zhubo.asia"
HEADERS = {"Authorization": f"Bearer {API_KEY}"}

# ━━━ Step 1: 上传参考图 + 创建任务 ━━━
files = [
    ("input_reference[]", ("ref1.jpg", open("ref1.jpg", "rb"), "image/jpeg")),
    ("input_reference[]", ("ref2.jpg", open("ref2.jpg", "rb"), "image/jpeg")),
]
resp = requests.post(f"{BASE}/v1/videos", headers=HEADERS,
    data={
        "model": "grok-imagine-video",
        "prompt": "两个角色在海边对决，电影级画质",
        "seconds": 6,
        "size": "1280x720",
    },
    files=files,
)
job = resp.json()
video_id = job["id"]
print(f"✅ 任务已创建: {video_id}")

# ━━━ Step 2: 轮询等待 ━━━
while True:
    r = requests.get(f"{BASE}/v1/videos/{video_id}", headers=HEADERS).json()
    print(f"   {r['status']} | {r.get('progress', 0)}%")
    if r["status"] == "completed":
        print(f"✅ 视频: {r['url']}")
        break
    elif r["status"] == "failed":
        print(f"❌ 失败: {r.get('error', {}).get('message')}")
        break
    time.sleep(5)
```

### Node.js 示例

```javascript
import fs from 'fs';

const API_KEY = 'sk-你的Key';
const BASE = 'https://grokai.zhubo.asia';

// Step 1: 创建任务
const form = new FormData();
form.append('model', 'grok-imagine-video');
form.append('prompt', '一只猫在月球上跳舞');
form.append('seconds', '6');
form.append('size', '1280x720');

// 如果有参考图：
// form.append('input_reference[]', new Blob([fs.readFileSync('ref.jpg')], {type: 'image/jpeg'}), 'ref.jpg');

const createResp = await fetch(`${BASE}/v1/videos`, {
  method: 'POST',
  headers: { Authorization: `Bearer ${API_KEY}` },
  body: form,
});
const job = await createResp.json();
console.log('任务ID:', job.id);

// Step 2: 轮询
while (true) {
  const r = await fetch(`${BASE}/v1/videos/${job.id}`, {
    headers: { Authorization: `Bearer ${API_KEY}` },
  }).then(r => r.json());

  console.log(`状态: ${r.status} | 进度: ${r.progress || 0}%`);
  if (r.status === 'completed') {
    console.log('视频地址:', r.url);
    break;
  }
  if (r.status === 'failed') {
    console.log('失败:', r.error?.message);
    break;
  }
  await new Promise(r => setTimeout(r, 5000));
}
```

---

## 6. 通过 Chat 接口生成视频

除了专用视频接口，也可以通过 Chat Completions 接口生成视频：

```
POST /v1/chat/completions
Content-Type: application/json
```

```json
{
  "model": "grok-imagine-video",
  "messages": [
    {"role": "user", "content": "一只猫在月球上跳舞"}
  ],
  "stream": true,
  "video_config": {
    "seconds": 6,
    "size": "1280x720",
    "resolution_name": "720p"
  }
}
```

Chat 模式下视频以流式进度推送，最终在 `content` 中返回视频 URL。

---

## 7. 错误码与排查

### HTTP 状态码

| 状态码 | 含义 |
|--------|------|
| `200` | 成功 |
| `400` | 请求参数错误（模型名/秒数/尺寸无效等） |
| `401` | API Key 缺失或无效 |
| `402` | 余额不足 |
| `502` | 上游服务异常（Token 过期等） |

### 常见错误与解决

| 错误信息 | 原因 | 解决 |
|----------|------|------|
| `Model 'xxx' is not a video model` | 模型名拼写错误 | 使用 `grok-imagine-video`、`grok-4.3-video` 或 `grok-4.3-video-heavy` |
| `seconds must be one of [6, 10, 12, 16, 20, 30]` | 不支持的视频时长 | 使用列表中的值 |
| `Field required` → `param: model` | 用了 JSON 格式发送请求 | 必须用 `multipart/form-data`（`-F` 而不是 `-d`） |
| `Video input reference upload failed: Asset upload returned 403` | 上游 Grok 账号 Token 过期或被风控 | 系统会自动重试其他账号；如持续报错请联系管理员刷新 Token 池 |
| `Video generation was blocked by content moderation` | 视频内容触发审核 | 修改 prompt 内容后重试 |
| `余额不足` | 账户余额为 0 | 充值后重试 |

---

## 8. 注意事项

1. **请求格式**: 视频接口必须使用 `multipart/form-data`（curl 用 `-F`，Python 用 `data=` + `files=`），**不支持 JSON body**
2. **参考图限制**: 最多 5 张，文件上传和 URL 可混合使用，总数不超过 5
3. **长视频**: 超过 10 秒的视频会自动分成多段生成并拼接，耗时更长
4. **视频保留**: 生成的视频文件保存在服务器本地，重启服务后仍可下载
5. **并发限制**: 同一 API Key 建议不要同时提交超过 3 个视频任务
6. **超时**: 单个视频任务最长 180 秒，超时将标记为 failed

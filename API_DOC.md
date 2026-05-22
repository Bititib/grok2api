# zhuboApi 接口文档

> **Base URL**: `https://grokai.zhubo.asia`
> **认证方式**: `Authorization: Bearer <API_KEY>` 或 `X-API-Key: <API_KEY>`

---

## 目录

1. [认证说明](#1-认证说明)
2. [模型列表](#2-模型列表)
3. [对话补全](#3-对话补全)
4. [Responses API](#4-responses-api)
5. [图像生成](#5-图像生成)
6. [图像编辑](#6-图像编辑)
7. [视频生成](#7-视频生成)
8. [余额查询](#8-余额查询)
9. [计费说明](#9-计费说明)
10. [可用模型速查表](#10-可用模型速查表)

---

## 1. 认证说明

所有 API 请求需要在请求头中携带 API Key，支持两种方式：

```
Authorization: Bearer sk-xxxxxxxxxxxxxxxx
```

或

```
X-API-Key: sk-xxxxxxxxxxxxxxxx
```

**错误码**:

| HTTP 状态码 | 含义 |
|---|---|
| `401` | API Key 缺失或无效 |
| `402` | 余额不足，请充值 |
| `403` | API Key 已禁用或过期 |

---

## 2. 模型列表

```
GET /v1/models
```

**响应示例**:
```json
{
  "object": "list",
  "data": [
    {"id": "grok-4.20-auto", "object": "model", "owned_by": "xai", "name": "Grok 4.20 Auto"},
    {"id": "grok-imagine-image", "object": "model", "owned_by": "xai", "name": "Grok Imagine Image"},
    ...
  ]
}
```

---

## 3. 对话补全

```
POST /v1/chat/completions
Content-Type: application/json
```

### 3.1 基础对话

```json
{
  "model": "grok-4.20-auto",
  "messages": [
    {"role": "user", "content": "你好"}
  ],
  "stream": false
}
```

### 3.2 流式对话

```json
{
  "model": "grok-4.20-auto",
  "messages": [
    {"role": "user", "content": "用一句话介绍你自己"}
  ],
  "stream": true
}
```

### 3.3 带思维链（Thinking）

```json
{
  "model": "grok-4.20-expert",
  "messages": [
    {"role": "user", "content": "计算 123 * 456"}
  ],
  "stream": false,
  "reasoning_effort": "high"
}
```

`reasoning_effort` 可选值: `none`, `minimal`, `low`, `medium`, `high`, `xhigh`

### 3.4 多模态（图片输入）

```json
{
  "model": "grok-4.20-auto",
  "messages": [
    {
      "role": "user",
      "content": [
        {"type": "text", "text": "描述这张图片"},
        {"type": "image_url", "image_url": {"url": "https://example.com/image.jpg"}}
      ]
    }
  ]
}
```

支持 URL 和 Base64 Data URI (`data:image/jpeg;base64,...`) 两种图片输入方式。

### 3.5 工具调用（Function Calling）

```json
{
  "model": "grok-4.20-auto",
  "messages": [
    {"role": "user", "content": "今天北京天气怎么样"}
  ],
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "get_weather",
        "description": "获取指定城市的天气",
        "parameters": {
          "type": "object",
          "properties": {
            "city": {"type": "string", "description": "城市名"}
          },
          "required": ["city"]
        }
      }
    }
  ],
  "tool_choice": "auto"
}
```

### 3.6 深度搜索（DeepSearch）

```json
{
  "model": "grok-4.20-auto",
  "messages": [
    {"role": "user", "content": "2025年全球AI芯片市场格局"}
  ],
  "deepsearch": "default"
}
```

`deepsearch` 可选值: `default`, `deeper`

### 3.7 图像生成（通过 Chat 接口）

```json
{
  "model": "grok-imagine-image",
  "messages": [
    {"role": "user", "content": "一只在太空漂浮的猫"}
  ],
  "image_config": {
    "n": 1,
    "size": "1024x1024",
    "response_format": "url"
  }
}
```

### 3.8 视频生成（通过 Chat 接口）

```json
{
  "model": "grok-imagine-video",
  "messages": [
    {"role": "user", "content": "一只猫在月球上跳舞"}
  ],
  "video_config": {
    "seconds": 6,
    "size": "720x1280",
    "resolution_name": "720p"
  }
}
```

**video_config 参数**:

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `seconds` | int | `6` | 视频时长（秒） |
| `size` | string | `720x1280` | 画幅尺寸 |
| `resolution_name` | string | `720p` | 分辨率: `480p` 或 `720p` |
| `preset` | string | - | 预设: `fun`, `normal`, `spicy`, `custom` |

`size` 可选值: `720x1280`, `1280x720`, `1024x1024`, `1024x1792`, `1792x1024`

### 响应示例（非流式）

```json
{
  "id": "chatcmpl-xxxxxxxx",
  "object": "chat.completion",
  "created": 1772765431,
  "model": "grok-4.20-auto",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "你好！有什么可以帮你的吗？"
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 12,
    "completion_tokens": 18,
    "total_tokens": 30
  }
}
```

---

## 4. Responses API

```
POST /v1/responses
Content-Type: application/json
```

兼容 OpenAI Responses API 格式。

```json
{
  "model": "grok-4.20-auto",
  "input": "解释一下量子隧穿",
  "stream": true,
  "instructions": "用简洁的语言回答",
  "reasoning": {
    "effort": "high"
  }
}
```

**请求参数**:

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `model` | string | ✅ | 模型名称 |
| `input` | string / array | ✅ | 输入内容 |
| `instructions` | string | - | 系统指令 |
| `stream` | bool | - | 是否流式输出 |
| `reasoning` | object | - | `{"effort": "high"}` 等 |
| `temperature` | float | - | 温度 (0~2) |
| `top_p` | float | - | Top-P (0~1) |
| `tools` | array | - | 工具定义 |
| `tool_choice` | string/object | - | 工具选择策略 |

---

## 5. 图像生成

```
POST /v1/images/generations
Content-Type: application/json
```

```json
{
  "model": "grok-imagine-image",
  "prompt": "一只在太空漂浮的猫",
  "n": 1,
  "size": "1024x1024",
  "response_format": "url"
}
```

**请求参数**:

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `model` | string | - | 图像模型名称（必填） |
| `prompt` | string | - | 图像描述（必填） |
| `n` | int | `1` | 生成数量 (1~10, lite 模型上限 4) |
| `size` | string | `1024x1024` | 图像尺寸 |
| `response_format` | string | `url` | 返回格式: `url` 或 `b64_json` |

`size` 可选值: `1280x720`, `720x1280`, `1792x1024`, `1024x1792`, `1024x1024`

**响应示例**:
```json
{
  "created": 1772765431,
  "data": [
    {"url": "https://..."}
  ]
}
```

---

## 6. 图像编辑

```
POST /v1/images/edits
Content-Type: multipart/form-data
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `model` | string | ✅ | `grok-imagine-image-edit` |
| `prompt` | string | ✅ | 编辑描述 |
| `image[]` | file | ✅ | 参考图片（支持多张） |
| `n` | int | - | 生成数量 (1~2) |
| `size` | string | - | 输出尺寸，默认 `1024x1024` |
| `response_format` | string | - | `url` 或 `b64_json` |

---

## 7. 视频生成

视频接口为**异步**模式：先提交创建任务，拿到 `video_id`，再轮询状态直到 `completed`。

### 7.1 创建视频任务

```
POST /v1/videos
Content-Type: multipart/form-data
```

**请求参数**:

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `model` | string | ✅ | - | 视频模型名（见下方可选值） |
| `prompt` | string | ✅ | - | 视频描述 |
| `seconds` | int | - | `6` | 时长：`6`, `10`, `12`, `16`, `20`, `30` |
| `size` | string | - | `720x1280` | 画幅 |
| `resolution_name` | string | - | `720p` | 分辨率: `480p` / `720p` |
| `preset` | string | - | - | 预设: `fun`, `normal`, `spicy`, `custom` |
| `input_reference[]` | file | - | - | 参考图片文件上传（最多 5 张） |
| `input_reference_url[]` | string | - | - | 参考图片 URL（最多 5 个） |

**可用模型**:

| 模型名 | 说明 |
|---|---|
| `grok-imagine-video` | 标准视频生成（推荐） |
| `grok-4.3-video` | Grok 4.3 视频 |
| `grok-4.3-video-heavy` | Grok 4.3 视频（Heavy 级账号池） |

**size 可选值**: `720x1280` (竖屏)、`1280x720` (横屏)、`1024x1024` (方形)、`1024x1792`、`1792x1024`

#### 示例 1：纯文字生成视频

```bash
curl -X POST https://grokai.zhubo.asia/v1/videos \
  -H "Authorization: Bearer sk-你的Key" \
  -F "model=grok-imagine-video" \
  -F "prompt=一只猫在月球上跳舞，科幻风格，电影级画质" \
  -F "seconds=6" \
  -F "size=1280x720"
```

#### 示例 2：带参考图片生成视频（本地文件上传）

```bash
curl -X POST https://grokai.zhubo.asia/v1/videos \
  -H "Authorization: Bearer sk-你的Key" \
  -F "model=grok-imagine-video" \
  -F "prompt=两个角色在街头激烈格斗，动作片风格" \
  -F "seconds=6" \
  -F "size=1280x720" \
  -F "input_reference[]=@/path/to/character_a.jpg" \
  -F "input_reference[]=@/path/to/character_b.jpg"
```

#### 示例 3：带参考图片生成视频（URL 方式）

```bash
curl -X POST https://grokai.zhubo.asia/v1/videos \
  -H "Authorization: Bearer sk-你的Key" \
  -F "model=grok-imagine-video" \
  -F "prompt=角色在赛道上飙车" \
  -F "seconds=10" \
  -F "size=1280x720" \
  -F "input_reference_url[]=https://example.com/car1.jpg" \
  -F "input_reference_url[]=https://example.com/car2.jpg"
```

**创建成功响应** (HTTP 200):

```json
{
  "id": "video_61be39094ee24240b27a09c673beb068",
  "object": "video",
  "created_at": 1779357896,
  "status": "queued",
  "model": "grok-imagine-video",
  "progress": 0,
  "prompt": "...",
  "seconds": "6",
  "size": "1280x720",
  "quality": "standard"
}
```

### 7.2 轮询视频状态

```
GET /v1/videos/{video_id}
```

建议每 **5 秒** 轮询一次。视频通常在 **30~180 秒**内生成完毕。

```bash
curl https://grokai.zhubo.asia/v1/videos/video_61be39094ee24240b27a09c673beb068 \
  -H "Authorization: Bearer sk-你的Key"
```

**生成中响应**:

```json
{
  "id": "video_61be39094ee24240b27a09c673beb068",
  "object": "video",
  "status": "processing",
  "progress": 65,
  "..."
}
```

**生成完成响应**:

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

**生成失败响应**:

```json
{
  "id": "video_xxx",
  "object": "video",
  "status": "failed",
  "error": {
    "message": "具体错误原因"
  }
}
```

### 7.3 下载视频文件

```
GET /v1/files/video?id={video_id}
```

返回 `video/mp4` 文件流，**无需认证**，可直接在浏览器中播放。

```bash
# 下载到本地
curl -o output.mp4 "https://grokai.zhubo.asia/v1/files/video?id=video_61be39094ee24240b27a09c673beb068"
```

也可使用旧路径（同样可用）：

```
GET /v1/videos/{video_id}/content
```

### 7.4 完整调用流程示例（Python）

```python
import time
import requests

API_KEY = "sk-你的Key"
BASE = "https://grokai.zhubo.asia"
HEADERS = {"Authorization": f"Bearer {API_KEY}"}

# 1. 创建视频任务
resp = requests.post(f"{BASE}/v1/videos", headers=HEADERS, data={
    "model": "grok-imagine-video",
    "prompt": "一只猫在月球上跳舞",
    "seconds": 6,
    "size": "1280x720",
})
job = resp.json()
video_id = job["id"]
print(f"任务已创建: {video_id}")

# 2. 轮询等待完成
while True:
    r = requests.get(f"{BASE}/v1/videos/{video_id}", headers=HEADERS).json()
    print(f"  状态: {r['status']} | 进度: {r.get('progress', 0)}%")
    if r["status"] == "completed":
        print(f"✅ 视频地址: {r['url']}")
        break
    elif r["status"] == "failed":
        print(f"❌ 失败: {r.get('error', {}).get('message', '未知错误')}")
        break
    time.sleep(5)
```

### 7.5 带参考图完整示例（Python）

```python
import time
import requests

API_KEY = "sk-你的Key"
BASE = "https://grokai.zhubo.asia"
HEADERS = {"Authorization": f"Bearer {API_KEY}"}

# 1. 上传参考图 + 创建任务
files = [
    ("input_reference[]", ("ref1.jpg", open("ref1.jpg", "rb"), "image/jpeg")),
    ("input_reference[]", ("ref2.jpg", open("ref2.jpg", "rb"), "image/jpeg")),
]
resp = requests.post(f"{BASE}/v1/videos", headers=HEADERS, data={
    "model": "grok-imagine-video",
    "prompt": "两个角色在海边对决",
    "seconds": 6,
    "size": "1280x720",
}, files=files)
job = resp.json()
video_id = job["id"]
print(f"任务已创建: {video_id}")

# 2. 轮询等待
while True:
    r = requests.get(f"{BASE}/v1/videos/{video_id}", headers=HEADERS).json()
    print(f"  状态: {r['status']} | 进度: {r.get('progress', 0)}%")
    if r["status"] in ("completed", "failed"):
        print(r.get("url") or r.get("error", {}).get("message"))
        break
    time.sleep(5)
```

### 7.6 常见错误与排查

| 错误信息 | HTTP | 原因 | 解决方案 |
|---|---|---|---|
| `Model 'xxx' is not a video model` | 400 | 模型名错误 | 使用 `grok-imagine-video` 等有效模型名 |
| `seconds must be one of [6, 10, 12, 16, 20, 30]` | 400 | 时长不在支持范围 | 使用支持的秒数值 |
| `Video input reference upload failed: Asset upload returned 403` | 502 | 上游账号 Token 过期或被风控 | 系统会自动重试换号；如持续出现请联系管理员刷新 Token 池 |
| `余额不足` | 402 | 账户余额已用完 | 请充值后重试 |

---

## 8. 余额查询

### 8.1 查询余额

```
GET /v1/billing/balance
```

**响应示例**:
```json
{
  "billing": true,
  "key_name": "用户A",
  "balance": 9.85,
  "total_charged": 0.15,
  "status": "active",
  "group": "default",
  "allowed_models": []
}
```

`allowed_models` 为空数组表示可使用所有模型。

### 8.2 查询用量明细

```
GET /v1/billing/usage?page=1&page_size=50
```

**可选参数**:

| 参数 | 类型 | 说明 |
|---|---|---|
| `start_time` | int | 起始时间（毫秒时间戳） |
| `end_time` | int | 结束时间（毫秒时间戳） |
| `page` | int | 页码，默认 `1` |
| `page_size` | int | 每页条数，默认 `50`，上限 `100` |

**响应示例**:
```json
{
  "balance": 9.85,
  "summary": {
    "total_requests": 42,
    "total_prompt_tokens": 12500,
    "total_completion_tokens": 8300,
    "total_tokens": 20800,
    "total_cost": 0.15,
    "success_count": 41,
    "error_count": 1
  },
  "items": [...],
  "total": 42,
  "page": 1
}
```

---

## 9. 计费说明

### 对话模型（按 Token 计费）

| 模型前缀 | 输入 ($/1M tokens) | 输出 ($/1M tokens) |
|---|---|---|
| `grok-4` / `grok-3` | $3.00 | $15.00 |
| `grok-4-mini` / `grok-3-mini` | $0.30 | $0.50 |
| `grok-3-fast` | $0.60 | $3.00 |

### 图像模型（按次计费）

| 模型 | 单价 ($/次) |
|---|---|
| `grok-imagine-image-lite` | $0.02 |
| `grok-imagine-image` | $0.04 |
| `grok-imagine-image-pro` | $0.06 |
| `grok-imagine-image-edit` | $0.04 |

### 视频模型（按秒 × 分辨率计费）

| 分辨率 | 单价 ($/秒) | 6 秒 | 10 秒 | 20 秒 | 30 秒 |
|---|---|---|---|---|---|
| 480p | $0.02 | $0.12 | $0.20 | $0.40 | $0.60 |
| 720p | $0.03 | $0.18 | $0.30 | $0.60 | $0.90 |

> 余额不足时 API 将返回 `402 Payment Required`。

---

## 10. 可用模型速查表

### 对话模型

| 模型名 | 说明 | 账号池 |
|---|---|---|
| `grok-4.20-fast` | 快速模式（非推理） | Basic+ |
| `grok-4.20-auto` | 自动模式 | Basic+ |
| `grok-4.20-expert` | 专家推理模式 | Basic+ |
| `grok-4.20-heavy` | 重型推理模式 | Heavy |
| `grok-4.3-beta` | Grok 4.3 测试版 | Super+ |
| `grok-4.20-0309` | 0309 快照 | Basic+ |
| `grok-4.20-0309-super` | 0309 快照 (Super) | Super+ |
| `grok-4.20-0309-heavy` | 0309 快照 (Heavy) | Heavy |
| `grok-4.20-multi-agent-0309` | 多智能体 | Heavy |

### 图像模型

| 模型名 | 说明 | 账号池 |
|---|---|---|
| `grok-imagine-image-lite` | 快速图像生成 | Basic+ |
| `grok-imagine-image` | 标准图像生成 | Super+ |
| `grok-imagine-image-pro` | 高质量图像生成 | Super+ |
| `grok-imagine-image-edit` | 图像编辑 | Super+ |

### 视频模型

| 模型名 | 说明 | 账号池 |
|---|---|---|
| `grok-imagine-video` | 标准视频生成 | Super+ |
| `grok-4.3-video` | Grok 4.3 视频（支持更长时长） | Super+ |
| `grok-4.3-video-heavy` | Grok 4.3 视频 (Heavy) | Heavy |

---

## 第三方客户端接入

兼容 OpenAI API 格式，可直接在以下客户端中使用：

| 设置项 | 值 |
|---|---|
| API Base URL | `https://grokai.zhubo.asia/v1` |
| API Key | 你的 `sk-` 开头的 API Key |
| Model | `grok-4.20-auto` 等 |

支持的客户端包括但不限于：ChatGPT-Next-Web、LobeChat、Open WebUI、Chatbox 等。

# Grok2API 接口文档

> **Base URL**: `http://localhost:8000`
> **后台管理密码**: `grok2api`（配置项 `app.app_key`）
> **API 密钥**: 当前未设置（`api_key` 为空，无需认证）

---

## 目录

1. [健康检查](#1-健康检查)
2. [模型列表](#2-模型列表)
3. [对话补全](#3-对话补全)
4. [Responses API](#4-responses-api)
5. [图像生成](#5-图像生成)
6. [图像编辑](#6-图像编辑)
7. [管理接口](#7-管理接口)

---

## 1. 健康检查

```
GET /health
```

**响应示例**:
```json
{"status": "ok"}
```

---

## 2. 模型列表

```
GET /v1/models
```

**请求头** (api_key 非空时需要):
```
Authorization: Bearer <API_KEY>
```

**响应示例**:
```json
{
  "object": "list",
  "data": [
    {"id": "grok-3", "object": "model", "owned_by": "grok2api@chenyme"},
    {"id": "grok-3-mini", "object": "model", "owned_by": "grok2api@chenyme"},
    {"id": "grok-3-thinking", "object": "model", "owned_by": "grok2api@chenyme"},
    {"id": "grok-4", "object": "model", "owned_by": "grok2api@chenyme"},
    {"id": "grok-4-mini", "object": "model", "owned_by": "grok2api@chenyme"},
    {"id": "grok-4-thinking", "object": "model", "owned_by": "grok2api@chenyme"},
    {"id": "grok-4-heavy", "object": "model", "owned_by": "grok2api@chenyme"},
    {"id": "grok-4.1-mini", "object": "model", "owned_by": "grok2api@chenyme"},
    {"id": "grok-4.1-fast", "object": "model", "owned_by": "grok2api@chenyme"},
    {"id": "grok-4.1-expert", "object": "model", "owned_by": "grok2api@chenyme"},
    {"id": "grok-4.1-thinking", "object": "model", "owned_by": "grok2api@chenyme"},
    {"id": "grok-4.20-beta", "object": "model", "owned_by": "grok2api@chenyme"},
    {"id": "grok-imagine-1.0-fast", "object": "model", "owned_by": "grok2api@chenyme"},
    {"id": "grok-imagine-1.0", "object": "model", "owned_by": "grok2api@chenyme"},
    {"id": "grok-imagine-1.0-edit", "object": "model", "owned_by": "grok2api@chenyme"},
    {"id": "grok-imagine-1.0-video", "object": "model", "owned_by": "grok2api@chenyme"}
  ]
}
```

---

## 3. 对话补全

```
POST /v1/chat/completions
```

**请求头**:
```
Content-Type: application/json
Authorization: Bearer <API_KEY>   # api_key 非空时需要
```

### 3.1 基础对话

```json
{
  "model": "grok-4",
  "messages": [
    {"role": "user", "content": "你好"}
  ],
  "stream": false
}
```

### 3.2 流式对话

```json
{
  "model": "grok-4",
  "messages": [
    {"role": "user", "content": "用一句话介绍你自己"}
  ],
  "stream": true
}
```

### 3.3 带思维链（Thinking）

```json
{
  "model": "grok-4-thinking",
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
  "model": "grok-4",
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

### 3.5 工具调用（Function Calling）

```json
{
  "model": "grok-4",
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

### 3.6 图像生成（通过 Chat 接口）

```json
{
  "model": "grok-imagine-1.0",
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

### 3.7 视频生成（通过 Chat 接口）

```json
{
  "model": "grok-imagine-1.0-video",
  "messages": [
    {"role": "user", "content": "一只猫在月球上跳舞"}
  ],
  "video_config": {
    "aspect_ratio": "16:9",
    "video_length": 6,
    "resolution_name": "480p"
  }
}
```

### 响应示例（非流式）:

```json
{
  "id": "xxx-xxx-xxx",
  "object": "chat.completion",
  "created": 1772765431,
  "model": "grok-4",
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
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "total_tokens": 0
  }
}
```

---

## 4. Responses API

```
POST /v1/responses
```

兼容 OpenAI Responses API 格式。

```json
{
  "model": "grok-4",
  "input": "解释一下量子隧穿",
  "stream": true,
  "reasoning": {
    "effort": "high"
  }
}
```

---

## 5. 图像生成

```
POST /v1/images/generations
```

```json
{
  "model": "grok-imagine-1.0",
  "prompt": "一只在太空漂浮的猫",
  "n": 1,
  "size": "1024x1024",
  "response_format": "url"
}
```

`size` 可选值: `1280x720`, `720x1280`, `1792x1024`, `1024x1792`, `1024x1024`

---

## 6. 图像编辑

```
POST /v1/images/edits
Content-Type: multipart/form-data
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `model` | string | `grok-imagine-1.0-edit` |
| `prompt` | string | 编辑描述 |
| `image` | file | 待编辑图片 (png/jpg/webp) |
| `n` | integer | 生成数量 (1~10) |

---

## 7. 管理接口

### 7.1 管理后台页面

```
GET /admin          → 管理面板（Token / 配置 / 缓存管理）
```

密码: `grok2api`

### 7.2 Token 管理 API

**请求头**（所有管理接口需要）:
```
X-App-Key: grok2api
```

#### 获取所有 Token
```
GET /v1/admin/tokens
```

#### 批量添加/更新 Token
```
POST /v1/admin/tokens
```
```json
{
  "ssoBasic": [
    "token_string_1",
    "token_string_2",
    {"token": "token_string_3", "note": "备注"}
  ],
  "ssoSuper": [
    "super_token_1"
  ]
}
```

#### 刷新 Token 状态
```
POST /v1/admin/tokens/refresh
```
```json
{
  "token": "token_string"
}
```

#### 批量刷新（异步 + SSE）
```
POST /v1/admin/tokens/refresh/async
```
```json
{
  "tokens": ["token1", "token2"]
}
```

#### 批量开启 NSFW
```
POST /v1/admin/tokens/nsfw
```
```json
{
  "tokens": ["token1", "token2"]
}
```

### 7.3 配置管理 API

#### 获取配置
```
GET /v1/admin/config
```

#### 更新配置
```
POST /v1/admin/config
```
```json
{
  "app": {"api_key": "your-secret-key"},
  "chat": {"timeout": 120}
}
```

### 7.4 缓存管理 API

```
GET  /v1/admin/cache      → 获取缓存状态
POST /v1/admin/cache/clean → 清理缓存
```

---

## 可用模型速查表

| 模型名 | 计次 | 可用账号 | 对话 | 图像 | 视频 |
|--------|:----:|---------|:----:|:----:|:----:|
| `grok-3` | 1 | Basic/Super | ✅ | ✅ | - |
| `grok-3-mini` | 1 | Basic/Super | ✅ | ✅ | - |
| `grok-3-thinking` | 1 | Basic/Super | ✅ | ✅ | - |
| `grok-4` | 1 | Basic/Super | ✅ | ✅ | - |
| `grok-4-mini` | 1 | Basic/Super | ✅ | ✅ | - |
| `grok-4-thinking` | 1 | Basic/Super | ✅ | ✅ | - |
| `grok-4-heavy` | 4 | Super | ✅ | ✅ | - |
| `grok-4.1-mini` | 1 | Basic/Super | ✅ | ✅ | - |
| `grok-4.1-fast` | 1 | Basic/Super | ✅ | ✅ | - |
| `grok-4.1-expert` | 4 | Basic/Super | ✅ | ✅ | - |
| `grok-4.1-thinking` | 4 | Basic/Super | ✅ | ✅ | - |
| `grok-4.20-beta` | 1 | Basic/Super | ✅ | ✅ | - |
| `grok-imagine-1.0` | - | Basic/Super | - | ✅ | - |
| `grok-imagine-1.0-fast` | - | Basic/Super | - | ✅ | - |
| `grok-imagine-1.0-edit` | - | Basic/Super | - | ✅ | - |
| `grok-imagine-1.0-video` | - | Basic/Super | - | - | ✅ |

---

## 配额说明

- **Basic 账号**: 80 次 / 20h
- **Super 账号**: 140 次 / 2h

---

## 第三方客户端接入

兼容 OpenAI API 格式，可直接在以下客户端中使用：

| 设置项 | 值 |
|--------|-----|
| API Base URL | `http://localhost:8000/v1` |
| API Key | 留空（或你设置的 `api_key`） |
| Model | `grok-4` 等 |

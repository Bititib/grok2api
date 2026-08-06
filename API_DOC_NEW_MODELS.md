# 新接入视频模型调用文档 (ld-sdas-h3 / sd2.0-480p)

本文档面向开发者及客户端（如微信机器人/WebUI），说明新接入的 **海螺 H3** 与 **Seedance 2.0 480p** 异步视频生成模型的调用规范、参数格式及计费说明。

---

## 1. 基础信息

* **接口网关 URL**：`https://grokai.zhubo.asia`
* **鉴权方式**：`Authorization: Bearer YOUR_API_KEY` （HTTP 请求头中携带）
* **接口特色**：网关已内置 **方案 B 自动媒体上传代理**。您的客户端在调用时，可以直接传入本地临时文件、Base64 编码的 `data:image/...`，或者其他任意域名的公网图片/音视频链接。网关会在后台自动处理文件解析并上传托管给上游平台，免去您客户端二次开发的繁琐流程。

---

## 2. 新增模型清单

| 模型 ID | 模型画质 | 计费类型 | 计费单价 | 最大时长 | 参考素材限制 | 适用场景及优势 |
|---|---|---|---|---|---|---|
| **`ld-sdas-h3-501-2k`** | **`2K` 极清** | **按次计费** | **3.50 元 / 次** | `5`–`15` 秒 | 图(5) / 视(0) / 音(1)<br>✅ 支持真人面部 | 海螺 H3 官方满血版，2K 画质极佳，画面表现逼真，生成速度快。 |
| **`ld-sdas-cvk-pro-933-720p`** | **`720p` 高清** | **按次计费** | **4.70 元 / 次** | `4`–`15` 秒 | 图(9) / 视(3) / 音(3)<br>✅ 支持真人面部 | Seedance 2.0 720p 满血版（速大水渠道），画质清晰，支持多模态参考与真人人脸保持。 |
| **`sd2.0-480p`** | **`480p` 标准** | **按秒计费** | **0.35 元 / 秒** | `4`–`15` 秒 | 图(9) / 视(3) / 音(3)<br>✅ 支持真人面部 | Seedance 2.0 480p 满血版，概率卡脸，非常适合漫剧、线图及真人分身。 |
| **`sd2.5`** | **`720p` 高清** | **按次计费** | **2.00 元 / 次** | `15` 秒 (固定) | 图(50) / 视(10) / 音(10) | Seedance 2.5 全能多模态视频模型（hre3渠道），支持多达 50 张图片、10 段视频及 10 段音频参考，固定 15 秒生成。 |

---

## 3. 接口调用指南

### 3.1 方案一：统一 JSON 接口（推荐）

推荐直接使用此接口。请求 Body 格式更加精简规范。

* **创建任务接口**：`POST /v1/video/create` 或 `POST /v1/video/generations`
* **查询任务接口**：`GET /v1/video/query?id=task_xxxxxx` 或 `GET /v1/videos/{task_id}`

#### 调用示例 1：调用海螺 `ld-sdas-h3-501-2k`（按次扣费 $3.50）
```bash
curl -X POST "https://grokai.zhubo.asia/v1/video/create" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "ld-sdas-h3-501-2k",
    "prompt": "一只戴着墨镜的泰迪熊走在沙滩上，镜头平稳向前推進，2K高画质，电影质感",
    "aspect_ratio": "16:9",
    "duration": 6,
    "images": [
      "https://example.com/teddy-ref.jpg"
    ]
  }'
```

#### 调用示例 2：调用 Seedance `sd2.0-480p`（按秒扣费，6秒共计 $2.10）
```bash
curl -X POST "https://grokai.zhubo.asia/v1/video/create" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "sd2.0-480p",
    "prompt": "@Image1 里的女孩走入充满樱花落下的动漫校园中，手插口袋自然微笑，参考 @Video1 运镜手法",
    "aspect_ratio": "9:16",
    "seconds": 6,
    "images": [
      "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAA..." # 直接支持传入 Base64 编码
    ],
    "video_refs": [
      "https://example.com/camera-ref.mp4"
    ]
  }'
```

---

### 3.2 方案二：OpenAI 兼容表单/多模态参考接口

如果您需要通过微信机器人等客户端直接模拟网页表单上传文件（Multipart/Form-Data），可调用此接口。

* **创建任务接口**：`POST /v1/videos`

#### cURL 表单文件上传调用示例：
```bash
curl -X POST "https://grokai.zhubo.asia/v1/videos" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -F "model=sd2.0-480p" \
  -F "prompt=让上传的女孩人像 @Image1 抬头看向镜头并轻微咬唇，电影感特写" \
  -F "duration=5" \
  -F "image_refs[]=@/path/to/local/girl_face.jpg"
```
*(网关会自动接收文件并在 VPS 本地保存并转化为托管 URL，最后投递给上游执行任务。提示词中的 `@Image1` 将自动指代为上传的首张图片)*

---

## 4. 任务状态轮询与结果

任务提交通道均为**异步执行**，返回 `task_id` 后客户端需以 `5 - 8 秒` 间隔查询结果。

### 4.1 查询接口：`GET /v1/video/query`
```bash
curl -X GET "https://grokai.zhubo.asia/v1/video/query?id=task_385412" \
  -H "Authorization: Bearer YOUR_API_KEY"
```

### 4.2 响应结果对照

#### A. 任务处理中（status = "in_progress"）
```json
{
  "id": "task_385412",
  "status": "in_progress",
  "progress": 45,
  "model": "sd2.0-480p",
  "video_url": null
}
```

#### B. 生成成功（status = "completed"）
```json
{
  "id": "task_385412",
  "status": "completed",
  "progress": 100,
  "model": "sd2.0-480p",
  "video_url": "https://grokai.zhubo.asia/v1/files/video?id=e38b5247-e327-4024-8ee5-3462d5375b48"
}
```
*(可以直接使用 `video_url` 进行无权播放或直接下载视频)*

#### C. 生成失败（status = "failed"）
```json
{
  "id": "task_385412",
  "status": "failed",
  "progress": 0,
  "model": "sd2.0-480p",
  "video_url": null,
  "error": {
    "message": "人脸匹配度过低，无法过审"
  }
}
```
*(任务失败会自动触发退款。您的用户面板在任务状态刷新为 `failed` 时，此条记录的消费金额 `cost` 会自动同步修正为 `$0.000000`)*

# Grok2API VPS 部署指南

## 服务器信息

| 项目 | 值 |
|------|-----|
| VPS IP | `172.245.16.80` |
| 服务端口 | `8000` |
| 项目路径 | `/opt/grok2api` |
| Git 仓库 | `https://github.com/Bititib/grok2api.git` |
| Docker 镜像标签 | `grok2api:billing` |
| 容器名称 | `grok2api` |

---

## ⚠️ 关键注意事项

> **Docker 部署使用的是 `image: grok2api:billing` 方式，不是 `build:` 方式。**
>
> 这意味着 `docker compose build` 和 `docker compose up --build` **不会生效**。
> 必须手动用 `docker build -t grok2api:billing` 重新构建镜像。

---

## 日常更新部署（最常用）

当本地代码修改并 push 到 GitHub 后，在 VPS 上执行：

```bash
# 1. 进入项目目录
cd /opt/grok2api

# 2. 拉取最新代码
git pull

# 3. 重建镜像（必须指定标签 grok2api:billing）
docker build -t grok2api:billing --no-cache .

# 4. 重启服务
docker compose down
docker compose up -d

# 5. 验证启动
docker logs grok2api --tail 10
```

### 一行命令版本

```bash
cd /opt/grok2api && git pull && docker build -t grok2api:billing --no-cache . && docker compose down && docker compose up -d && docker logs grok2api --tail 10
```

---

## 查看日志

```bash
# 查看最近日志
docker logs grok2api --tail 50

# 实时跟踪日志
docker logs grok2api -f

# 搜索上行请求日志（检查 payload 是否正确）
docker logs grok2api --tail 50 | grep "upstream request"

# 搜索错误日志
docker logs grok2api --tail 100 | grep -i "error"
```

---

## 服务管理

```bash
# 查看容器状态
docker ps

# 停止服务
docker compose down

# 启动服务
docker compose up -d

# 重启服务（不重建镜像）
docker compose restart

# 进入容器内部调试
docker exec -it grok2api /bin/sh
```

---

## docker-compose.yml 结构

```yaml
services:
  grok2api:
    container_name: grok2api
    image: grok2api:billing          # ← 使用本地镜像标签
    ports:
      - "8000:8000"
    environment:
      - TZ=Asia/Shanghai
      - LOG_LEVEL=INFO
      - SERVER_HOST=0.0.0.0
      - SERVER_PORT=8000
      - SERVER_WORKERS=1
      - ACCOUNT_STORAGE=local
    volumes:
      - ./data:/app/data             # 数据持久化
      - ./logs:/app/logs             # 日志持久化
      - ./setting.toml:/app/setting.toml  # 配置文件
    restart: unless-stopped
```

---

## 本地开发 → VPS 部署完整流程

```
┌─────────────────────────────────────────┐
│  本地开发（Windows）                      │
│                                         │
│  1. 修改代码                              │
│  2. 本地测试 (http://127.0.0.1:8001)     │
│  3. git add → git commit → git push     │
└──────────────┬──────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────┐
│  VPS 部署（SSH 到 172.245.16.80）        │
│                                         │
│  1. cd /opt/grok2api                    │
│  2. git pull                            │
│  3. docker build -t grok2api:billing    │
│     --no-cache .                        │
│  4. docker compose down                 │
│  5. docker compose up -d               │
│  6. docker logs grok2api --tail 10      │
└─────────────────────────────────────────┘
```

---

## Git 操作

```bash
# 本地推送到 GitHub（在 Windows 上）
git add -A
git commit -m "fix: 描述修改内容"
git push bititib main

# VPS 拉取（在 VPS 上）
cd /opt/grok2api
git pull
```

---

## 配置文件

### setting.toml

位于 `/opt/grok2api/setting.toml`，通过 volume 挂载到容器内 `/app/setting.toml`。

修改配置后只需重启容器，不需要重建镜像：

```bash
# 编辑配置
vi /opt/grok2api/setting.toml

# 重启生效
docker compose restart
```

---

## 故障排查

### 问题：代码更新后 VPS 行为没变

**原因**：镜像没有重建。

```bash
# 确认 git 版本
cd /opt/grok2api && git log --oneline -3

# 强制重建镜像
docker build -t grok2api:billing --no-cache .
docker compose down && docker compose up -d
```

### 问题：容器启动失败

```bash
# 查看完整启动日志
docker logs grok2api

# 检查端口占用
netstat -tlnp | grep 8000
```

### 问题：验证上行 payload 格式

```bash
# 发送请求后立即查看
docker logs grok2api --tail 5 | grep "upstream request"

# 关键字段检查：
# ✅ "modelName":"imagine-video-gen"    （视频模型）
# ✅ "imageReferences":["...?token="]   （带认证 token）
# ✅ "fileAttachments":["..."]          （文件附件）
# ❌ "modelName":"grok-3"              （旧代码，需要重建镜像）
```

### 问题：磁盘空间不足

```bash
# 清理 Docker 缓存
docker system prune -af

# 查看磁盘使用
df -h
```

---

## 接口测试

### 快速健康检查

```bash
# 从 VPS 本地测试
curl http://127.0.0.1:8000/v1/models -H "Authorization: Bearer sk-901dcb75e85f5c3ae76a20f8d5f26df2"
```

### 从本地 Windows 测试

```bash
# 测试全部接口（在本地项目目录执行）
node test_api_vps.mjs
```

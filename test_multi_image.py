"""
多参考图视频生成测试脚本(omni-flash r2v)

用法:
    1. 改 KEY / BASE / IMAGES / PROMPT / DURATION
    2. uv pip install requests
    3. python test_multi_image.py

最多 7 张参考图。images 可以是 URL 或 data URI(base64)。
"""
import requests
import time
import base64
import sys

# ============ 改这里 ============
BASE = "https://llm.zerofall.top"             # NewAPI 地址(改成你的 NewAPI host)
KEY  = "sk-"  # 你的 NewAPI token

PROMPT = "两个角色在战斗"
DURATION = 4                                # 4 / 6 / 8 / 10
ASPECT_RATIO = "landscape"                  # landscape / portrait

# 1-7 张参考图,支持 URL 或本地路径(本地会自动转 base64)
IMAGES = [
    "/www/wwwroot/flow2api/fluchw_Epic_anime_girl_with_glowing_wings_of_fire_flying_thro_349eb581-3122-430a-aaa5-85fef0883e36_0.png",
    "/www/wwwroot/flow2api/gen_1778567869946_0.png",
]
# ============ 改这里结束 ============


def to_data_uri(path: str) -> str:
    """本地路径 → data:image/...;base64,..."""
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    mime = "image/png" if path.lower().endswith(".png") else "image/jpeg"
    return f"data:{mime};base64,{b64}"


def prepare_images(items):
    """把混合的 URL / 本地路径归一化成 [URL or data URI] 列表,最多 7 张"""
    if not items:
        return []
    out = []
    for it in items[:7]:                    # 最多 7 张(Omni Flash r2v 上限)
        it = it.strip()
        if not it:
            continue
        if it.startswith("http://") or it.startswith("https://") or it.startswith("data:"):
            out.append(it)
        else:
            out.append(to_data_uri(it))     # 本地文件
    return out


def main():
    headers = {"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}
    images = prepare_images(IMAGES)
    print(f"图片张数: {len(images)}")
    if not images:
        print("⚠️  没有图片,退化成纯文生视频(t2v)")

    # ===== 1) 提交 =====
    body = {
        "model": "omni-flash",
        "prompt": PROMPT,
        "duration": DURATION,
        "aspect_ratio": ASPECT_RATIO,
        "images": images,                   # 数组,后端按数量决定 r2v
    }
    print(f"\n[POST] {BASE}/v1/video/generations")
    t0 = time.time()
    r = requests.post(f"{BASE}/v1/video/generations", headers=headers, json=body)
    print(f"  HTTP {r.status_code}  elapsed {time.time()-t0:.1f}s")
    print(f"  resp: {r.text[:300]}")

    if r.status_code != 200:
        print("提交失败,退出")
        sys.exit(1)

    task_id = r.json().get("task_id")
    if not task_id:
        print("响应里没 task_id,退出")
        sys.exit(1)
    print(f"  task_id: {task_id}")

    # ===== 2) 轮询 =====
    print(f"\n开始轮询(每 10 秒,最长 10 分钟)...")
    poll_start = time.time()
    for i in range(60):
        time.sleep(10)
        rr = requests.get(f"{BASE}/v1/video/generations/{task_id}", headers=headers)
        if rr.status_code != 200:
            print(f"  HTTP {rr.status_code}  {rr.text[:200]}")
            continue
        data = rr.json().get("data", {})
        status = data.get("status", "?")
        progress = data.get("progress", "-")
        elapsed = time.time() - poll_start
        print(f"  t={elapsed:.0f}s  status={status}  progress={progress}")

        if status == "SUCCESS":
            inner = data.get("data", {})
            print(f"\n✅ 成功 (总耗时 {elapsed:.0f}s)")
            print(f"   video URL: {inner.get('url')}")
            print(f"   format:    {inner.get('format')}")
            print(f"   metadata:  {inner.get('metadata')}")
            return
        if status in ("FAILURE", "failed"):
            print(f"\n❌ 失败")
            print(f"   reason: {data.get('fail_reason') or data.get('error')}")
            return

    print(f"\n⏱️  10 分钟还没结束,退出轮询(task 后台可能仍在跑,稍后再 GET 查)")


if __name__ == "__main__":
    main()

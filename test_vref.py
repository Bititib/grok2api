"""
视频编辑 / 参考视频测试脚本(omni-flash-vref,abra_edit)

用法:
    1. 改 KEY / BASE / VIDEO / IMAGES / PROMPT
    2. uv pip install requests
    3. python test_vref.py

输入:1 个参考视频(必填)+ 0~5 张参考图(可选)。
  - IMAGES 为空 → 纯视频编辑(prompt 改写整段视频风格/光照)
  - IMAGES 非空 → 视频 + 参考图引导(最多 5 张)
video / images 都支持 URL 或本地路径(本地会自动转 base64 data URI)。

模型名:omni-flash-vref(独立裸名,横竖屏走 aspect_ratio 字段)。
duration:固定 10(必传且只接受 10),实际输出时长跟随输入参考视频。
仅 Ultra(PAYGATE_TIER_TWO)号可跑,40 积分/次。
"""
import requests
import time
import base64
import sys

# ============ 改这里 ============
BASE = "https://llm.zerofall.top"             # NewAPI 地址(改成你的 NewAPI host)
KEY  = "sk-"  # 你的 NewAPI token

PROMPT = "make it cinematic, dramatic lighting, vivid colors"
ASPECT_RATIO = "landscape"                  # landscape / portrait

# 1 个参考视频(必填),URL 或本地路径,≤30s
VIDEO = "https://test-videos.co.uk/vids/bigbuckbunny/mp4/h264/360/Big_Buck_Bunny_360_10s_1MB.mp4"

# 0-5 张参考图,支持 URL 或本地路径;留空 [] = 纯视频编辑
IMAGES = [
    # "/www/wwwroot/flow2api/gen_1778567869946_0.png",
]
# ============ 改这里结束 ============

DURATION = 10                               # vref 固定 10(必传且只接受 10)


def to_data_uri(path: str, kind: str) -> str:
    """本地路径 → data:<mime>;base64,...;kind = image | video"""
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    if kind == "video":
        mime = "video/mp4"
    else:
        mime = "image/png" if path.lower().endswith(".png") else "image/jpeg"
    return f"data:{mime};base64,{b64}"


def normalize(item: str, kind: str) -> str:
    """URL / data URI 原样;本地路径转 data URI"""
    item = item.strip()
    if item.startswith(("http://", "https://", "data:")):
        return item
    return to_data_uri(item, kind)


def prepare_images(items):
    out = []
    for it in (items or [])[:5]:             # vref 参考图最多 5 张
        if it and it.strip():
            out.append(normalize(it, "image"))
    return out


def main():
    if not VIDEO or not VIDEO.strip():
        print("VIDEO 不能为空(vref 必须有 1 个参考视频)")
        sys.exit(1)

    video = normalize(VIDEO, "video")
    images = prepare_images(IMAGES)
    mode = f"视频 + {len(images)} 张参考图" if images else "纯视频编辑(0 图)"
    print(f"模式: {mode}")

    url = f"{BASE}/v1/video/generations"
    headers = {"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}
    payload = {
        # 独立裸名,横竖屏走 aspect_ratio 字段(不写进模型名)
        "model": "omni-flash-vref",
        "prompt": PROMPT,
        "duration": DURATION,                # 必传,vref 只接受 10
        "aspect_ratio": ASPECT_RATIO,        # landscape / portrait
        "video": video,                      # 参考视频(单个);也可用 "video_url"
    }
    if images:
        payload["images"] = images           # 参考图 0-5 张;单张也可用 "image"

    print(f"\n[POST] {url}")
    t0 = time.time()
    resp = requests.post(url, headers=headers, json=payload, timeout=120)
    print(f"  HTTP {resp.status_code}  elapsed {time.time()-t0:.1f}s")
    if resp.status_code != 200:
        print(f"  resp: {resp.text}")
        print("提交失败,退出")
        sys.exit(1)

    data = resp.json()
    task_id = data.get("task_id") or data.get("id")
    print(f"  task_id: {task_id}")

    # 轮询
    poll_url = f"{BASE}/v1/video/generations/{task_id}"
    for i in range(120):
        time.sleep(5)
        r = requests.get(poll_url, headers=headers, timeout=30)
        st = r.json()
        status = st.get("status", "")
        print(f"  [{i}] status={status}")
        if status in ("completed", "succeeded"):
            print(f"\n✅ 完成: {st.get('url') or st.get('metadata')}")
            break
        if status in ("failed", "error"):
            print(f"\n❌ 失败: {st.get('error')}")
            break


if __name__ == "__main__":
    main()

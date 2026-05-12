"""
本地测试：验证视频 payload 格式是否与官方 grok.com 一致。
用 Python 3.9 兼容的语法重写目标函数来测试逻辑。
"""
import json, sys

# --- 复制自 video.py 的关键函数（改成 3.9 兼容语法）---

_PRESET_FLAGS = {
    "fun":    "--mode=fun",
    "normal": "--mode=normal",
    "spicy":  "--mode=spicy",
    "custom": "--mode=custom",
}
_VIDEO_MODEL_NAME = "imagine-video-gen"


def _build_message(prompt, preset, reference_file_ids=None):
    message = "{} {}".format(prompt, _PRESET_FLAGS.get(preset, '--mode=custom')).strip()
    if reference_file_ids:
        refs = " ".join("@{}".format(fid) for fid in reference_file_ids)
        return "{} {}".format(refs, message)
    return message


def _video_create_payload(
    prompt, parent_post_id, aspect_ratio, resolution_name,
    video_length, preset, mode_id=None,
    reference_file_ids=None, reference_content_urls=None,
):
    video_config = {
        "parentPostId": parent_post_id,
        "aspectRatio": aspect_ratio,
        "videoLength": video_length,
        "resolutionName": resolution_name,
    }
    if reference_content_urls:
        video_config["imageReferences"] = reference_content_urls
        video_config["isReferenceToVideo"] = True
        video_config["isVideoEdit"] = False

    payload = {
        "temporary": True,
        "modelName": _VIDEO_MODEL_NAME,
        "message": _build_message(prompt, preset, reference_file_ids=reference_file_ids),
        "toolOverrides": {"videoGen": True},
        "enableSideBySide": True,
        "responseMetadata": {
            "experiments": [],
            "modelConfigOverride": {
                "modelMap": {
                    "videoGenModelConfig": video_config,
                }
            },
        },
    }
    if mode_id:
        payload["modeId"] = mode_id
    return payload


# --- 测试 ---

print("=== 本地 Payload 格式验证 ===\n")
passed = 0
failed = 0

def test(name, fn):
    global passed, failed
    try:
        fn()
        passed += 1
        print("✅ {}".format(name))
    except AssertionError as e:
        failed += 1
        print("❌ {} → {}".format(name, e))


def test_msg_no_ref():
    msg = _build_message("一只猫跳舞", "custom")
    assert "@" not in msg
    assert "一只猫跳舞" in msg
test("_build_message 无参考图", test_msg_no_ref)


def test_msg_with_refs():
    fids = ["c975e477-5466", "4143d0c2-325b", "edacbe51-32bd"]
    msg = _build_message("图片中的人物在打架", "custom", reference_file_ids=fids)
    for fid in fids:
        assert "@{}".format(fid) in msg, "缺少 @{}".format(fid)
    assert "@Image" not in msg, "不应有 @Image N"
    assert msg.endswith("--mode=custom")
    print("   消息: {}".format(msg))
test("_build_message @file_id 格式", test_msg_with_refs)


def test_payload_no_ref():
    p = _video_create_payload(
        prompt="一只猫", parent_post_id="post-123",
        aspect_ratio="9:16", resolution_name="720p",
        video_length=6, preset="custom",
    )
    cfg = p["responseMetadata"]["modelConfigOverride"]["modelMap"]["videoGenModelConfig"]
    assert "imageReferences" not in cfg
    assert "isReferenceToVideo" not in cfg
    assert "fileAttachments" not in p
test("payload 无参考图 — 干净", test_payload_no_ref)


def test_payload_with_refs():
    fids = ["c975e477-5466-4e0c-a0f5-7e82488c21e1", "4143d0c2-325b-4607", "edacbe51-32bd-45a7"]
    urls = [
        "https://assets.grok.com/users/u1/{}/content?cache=1".format(f) for f in fids
    ]
    p = _video_create_payload(
        prompt="图片中的人物在打架",
        parent_post_id="bfecc0b4-6093",
        aspect_ratio="9:16", resolution_name="720p",
        video_length=10, preset="custom",
        reference_file_ids=fids, reference_content_urls=urls,
    )
    cfg = p["responseMetadata"]["modelConfigOverride"]["modelMap"]["videoGenModelConfig"]

    assert "imageReferences" in cfg, "缺少 imageReferences"
    assert cfg["imageReferences"] == urls
    assert cfg["isReferenceToVideo"] is True
    assert cfg["isVideoEdit"] is False
    for fid in fids:
        assert "@{}".format(fid) in p["message"]
    assert "fileAttachments" not in p

    print("   message: {}".format(p["message"][:80]))
    print("   imageReferences: {} 个 ✓".format(len(cfg["imageReferences"])))
    print("   isReferenceToVideo: {} ✓".format(cfg["isReferenceToVideo"]))
    print("   isVideoEdit: {} ✓".format(cfg["isVideoEdit"]))
test("payload 对齐官方格式", test_payload_with_refs)


def test_full_payload():
    p = _video_create_payload(
        prompt="图片中的人物在相互打架",
        parent_post_id="bfecc0b4-6093-449a",
        aspect_ratio="9:16", resolution_name="720p",
        video_length=10, preset="custom",
        reference_file_ids=["c975e477", "4143d0c2", "edacbe51"],
        reference_content_urls=[
            "https://assets.grok.com/users/u1/c975e477/content?cache=1",
            "https://assets.grok.com/users/u1/4143d0c2/content?cache=1",
            "https://assets.grok.com/users/u1/edacbe51/content?cache=1",
        ],
    )
    print("\n   === 生成的 Payload (与官方对比) ===")
    print("   " + json.dumps(p, indent=2, ensure_ascii=False).replace("\n", "\n   "))
test("完整 payload 输出", test_full_payload)


print("\n" + "=" * 50)
print("验证完成: ✅ {} 通过, ❌ {} 失败".format(passed, failed))
print("=" * 50)
sys.exit(1 if failed > 0 else 0)

import os
import sys
import json
from pathlib import Path
from typing import List, Tuple

try:
    # DrissionPage v4 推荐写法
    from DrissionPage import ChromiumOptions, ChromiumPage
except ImportError:  # pragma: no cover - 运行时错误提示
    print("未找到 DrissionPage，请先在当前虚拟环境中安装：pip install DrissionPage")
    sys.exit(1)


BASE_PROFILES_DIR = Path("d:/ChromeProfiles")
GROK_URL = "https://grok.com"


def scan_profiles(base_dir: Path) -> List[Path]:
    """扫描 d:/ChromeProfiles 下的 Profile 目录。

    只识别类似 Profile_0、Profile_1 这类目录，避免把 Chrome 的内部数据目录算进去。
    """
    if not base_dir.exists():
        print(f"目录不存在：{base_dir}")
        return []
    # 只匹配 Profile_*，与 auto_import_grok_tokens 中的逻辑保持一致
    profiles = sorted(
        [p for p in base_dir.glob("Profile_*") if p.is_dir()],
        key=lambda p: p.name.lower(),
    )
    # 如果完全没有 Profile_*，退而求其次只提示一下，避免用户疑惑
    if not profiles:
        print("未找到任何 Profile_* 目录，请确认已从 Chrome 复制 Profile。")
        return []
    # 按名称排序，方便用户选择
    return profiles


def choose_profiles(profiles: List[Path]) -> List[Path]:
    """交互式选择一个或多个 Profile。

    - 输入数字序号选择单个
    - 使用逗号分隔选择多个，例如: 1,3,5
    - 输入 0 或 all 代表全部
    """
    if not profiles:
        print("未找到任何 Profile 目录。")
        return []

    print("\n发现以下 Profile：")
    for idx, p in enumerate(profiles, start=1):
        print(f"[{idx}] {p.name}  ({p})")
    print("[0] 全部 Profile")

    while True:
        raw = input("\n请选择要登录的 Profile（例如：1 或 1,3,5 或 0 表示全部）：").strip()
        if raw.lower() in ("0", "all", "a"):
            return profiles

        try:
            indexes = [int(x.strip()) for x in raw.split(",") if x.strip()]
        except ValueError:
            print("输入格式不正确，请输入数字或用逗号分隔的数字。")
            continue

        # 去重并过滤非法序号
        valid_set = {i for i in indexes if 1 <= i <= len(profiles)}
        if not valid_set:
            print("没有有效的序号，请重新输入。")
            continue

        return [profiles[i - 1] for i in sorted(valid_set)]


def open_browser_and_login(profile_dir: Path, target_url: str, login_type: str) -> List[dict]:
    """为指定 Profile 打开浏览器，跳转到目标登录页，等待用户手动登录并返回 Cookies。

    为了用户友好：
    - 浏览器会保持打开状态
    - 控制台中提示用户完成登录后按回车
    """
    print(f"\n=== 使用 Profile：{profile_dir} 登录 {login_type} ===")

    # 使用指定 Profile 的 user data 目录
    co = ChromiumOptions()
    # 若 profile 结构为 d:/ChromeProfiles/Profile 直接当作 user_data_path 使用
    co.set_user_data_path(str(profile_dir))

    # 若你的 Chrome 安装路径不是默认路径，可以在这里设置：
    # co.set_browser_path(r"C:\Path\To\chrome.exe")

    page = ChromiumPage(co)
    page.get(target_url)

    print("浏览器已打开，请在浏览器中手动完成登录流程。")
    input("完成登录后，请返回此窗口并按回车提取 Cookies ...")

    # DrissionPage 的 cookies 接口：all_info=True 可包含 domain/path 等信息
    cookies = page.cookies(all_info=True)
    print(f"已获取到 {len(cookies)} 条 Cookie。")
    return cookies


def display_cookies(profile_dir: Path, login_type: str, cookies: List[dict]) -> None:
    """以较友好的格式打印 Cookies，并输出为 JSON。"""
    print(f"\n=== Profile: {profile_dir.name} | 登录方式: {login_type} 的 Cookies ===")

    # 简要列表
    for c in cookies[:10]:
        name = c.get("name")
        domain = c.get("domain")
        value = c.get("value")
        print(f"- {name} @ {domain} = {value}")
    if len(cookies) > 10:
        print(f"... 共 {len(cookies)} 条，已省略显示部分。")

    # 完整 JSON 输出，方便复制保存
    cookies_json = json.dumps(cookies, ensure_ascii=False, indent=2)
    print("\n完整 Cookies JSON：")
    print(cookies_json)


def main() -> None:
    """主流程：

    1. 扫描 d:/ChromeProfiles 下的所有 Profile
    2. 交互式选择 Profile（单个 / 多个 / 全部）
    3. 为每个 Profile 打开 Grok 登录页面
    4. 逐个 Profile 打开浏览器，让用户手动登录
    5. 登录完成后自动提取并展示 Cookies
    """
    print("=== 基于 DrissionPage 的 Grok 多 Profile 登录与 Cookie 提取工具 ===")
    print(f"Profile 根目录：{BASE_PROFILES_DIR}")

    profiles = scan_profiles(BASE_PROFILES_DIR)
    if not profiles:
        return

    selected_profiles = choose_profiles(profiles)
    if not selected_profiles:
        print("未选择任何 Profile，程序结束。")
        return

    # 固定为 Grok 登录场景
    login_type = "Grok"
    url = GROK_URL

    for profile in selected_profiles:
        try:
            cookies = open_browser_and_login(profile, url, login_type)
            display_cookies(profile, login_type, cookies)
        except Exception as e:  # pragma: no cover - 仅用于运行时保护
            print(f"Profile {profile} 登录或提取 Cookie 时出错：{e}")

    print("\n全部 Profile 处理完成。您可以根据需要手动关闭已打开的浏览器窗口。")


if __name__ == "__main__":
    main()



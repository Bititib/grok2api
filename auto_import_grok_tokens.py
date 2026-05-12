"""
批量从本地 Chrome Profile 中提取 Grok 的 sso Cookie，
并通过 grok2api 管理接口批量导入为 Token。

参考 flow2api 的实现方式，使用 DrissionPage 直接使用 Chrome Profile。

使用前提：
1. 每个账号对应一个 Chrome Profile 目录，例如：
   D:\\ChromeProfiles\\Profile_0
   D:\\ChromeProfiles\\Profile_1
   ...
2. 你已经使用这些 Profile 手动登录过 Google + Grok，并保持登录状态。
3. grok2api 服务已在本地运行，例如：http://localhost:8001

依赖安装（建议在虚拟环境中手动安装）：
    pip install DrissionPage requests

然后在项目根目录 D:\\grok2api\\grok2api 下运行：
    python auto_import_grok_tokens.py
"""

import json
from pathlib import Path
from typing import List, Optional, Dict, Any

import requests
try:
    from DrissionPage import ChromiumPage, ChromiumOptions
except ImportError:
    print("[ERROR] 请先安装 DrissionPage: pip install DrissionPage")
    raise


# ===== 基本配置 =====
# grok2api 服务地址
BASE_URL = "http://localhost:8001"

# 管理后台账号（如未改动配置则为 admin/admin）
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin"

# Chrome Profiles 根目录
PROFILE_ROOT = Path(r"D:\ChromeProfiles")

# Token 类型：
# - "sso"      => 普通账号
# - "ssoSuper" => Super 账号
TOKEN_TYPE = "sso"


def iter_profile_dirs(root: Path) -> List[Path]:
    """
    遍历根目录下的 Profile_* 子目录，每个目录视为一个账号 Profile。
    """
    if not root.exists():
        raise RuntimeError(f"Profile 根目录不存在: {root}")

    dirs: List[Path] = []
    for p in root.iterdir():
        # 仅处理类似 Profile_0 / Profile_1 的目录
        if p.is_dir() and p.name.startswith("Profile_"):
            dirs.append(p)

    # 按名称排序，方便查看
    dirs.sort(key=lambda x: x.name)
    return dirs


def get_email_from_preferences(profile_dir: Path) -> Optional[str]:
    """
    从 Preferences 文件中读取邮箱（参考 flow2api 的实现）。
    """
    # 查找 Default 或 Profile 1 等子目录
    default_dir = profile_dir / "Default"
    profile_1_dir = profile_dir / "Profile 1"
    
    profile_subdir = None
    if default_dir.exists():
        profile_subdir = default_dir
    elif profile_1_dir.exists():
        profile_subdir = profile_1_dir
    else:
        # 如果没有标准子目录，尝试直接使用 profile_dir
        profile_subdir = profile_dir
    
    prefs_file = profile_subdir / "Preferences"
    
    if not prefs_file.exists():
        return None
    
    try:
        with open(prefs_file, 'r', encoding='utf-8') as f:
            prefs = json.load(f)
            
            # 尝试多个可能的路径（参考 flow2api）
            # 1. account_info 数组
            if 'account_info' in prefs:
                if isinstance(prefs['account_info'], list) and len(prefs['account_info']) > 0:
                    email = prefs['account_info'][0].get('email')
                    if email:
                        return email
                elif isinstance(prefs['account_info'], dict):
                    email = prefs['account_info'].get('email')
                    if email:
                        return email
            
            # 2. profile.user_name
            if 'profile' in prefs and isinstance(prefs['profile'], dict):
                email = prefs['profile'].get('user_name')
                if email:
                    return email
                email = prefs['profile'].get('name')
                if email:
                    return email
            
            # 3. signin.allowed_username
            if 'signin' in prefs and isinstance(prefs['signin'], dict):
                email = prefs['signin'].get('allowed_username', '')
                if email:
                    return email
    except Exception as e:
        # 静默失败，不打印错误（因为很多 Profile 可能没有邮箱信息）
        pass
    
    return None


def get_sso_from_profile(profile_dir: Path) -> Optional[str]:
    """
    使用 DrissionPage 直接使用 Chrome Profile，访问 grok.com 并提取 sso Cookie。
    参考 flow2api 的实现方式。
    """
    profile_name = profile_dir.name
    print(f"\n[处理] {profile_name}...")
    
    # 从 Preferences 读取邮箱
    email = get_email_from_preferences(profile_dir)
    if email:
        print(f"  → 邮箱: {email}")
    else:
        print(f"  → ⚠️ 未找到邮箱信息")
    
    page = None
    try:
        # 配置浏览器（参考 flow2api 的方式）
        co = ChromiumOptions()
        
        # 设置 user_data_path 为父目录（D:\ChromeProfiles）
        parent_dir = profile_dir.parent
        co.set_paths(user_data_path=str(parent_dir))
        
        # 设置 profile-directory（如 Profile_0）
        co.set_argument(f'--profile-directory={profile_name}')
        
        # 设置无头模式（通过 ChromiumOptions）
        co.headless(True)
        
        # 启动浏览器
        print(f"  → 启动浏览器（无头模式）...")
        page = ChromiumPage(co)
        
        # 访问 grok.com
        print(f"  → 访问 grok.com...")
        page.get('https://grok.com')
        
        # 等待页面加载
        page.wait(3)
        
        # 获取 cookies
        cookies_list = page.cookies()
        cookies = {}
        if isinstance(cookies_list, list):
            for cookie in cookies_list:
                if isinstance(cookie, dict) and 'name' in cookie and 'value' in cookie:
                    cookies[cookie['name']] = cookie['value']
        
        # 查找 sso cookie
        sso = cookies.get('sso')
        
        # 检查是否有 Google cookies（确认是否登录了 Google 账号）
        has_google = any('google.com' in str(cookie.get('domain', '')) for cookie in cookies_list if isinstance(cookie, dict))
        
        # 关闭浏览器
        page.quit()
        
        if sso:
            print(f"  → ✓ 找到 SSO: {sso[:20]}...")
            if has_google:
                print(f"  → ✓ 已登录 Google")
            return sso
        else:
            print(f"  → ✗ 未找到 SSO Cookie")
            if has_google:
                print(f"  → ✓ 已登录 Google（但未登录 Grok）")
            return None
            
    except Exception as e:
        print(f"  → ✗ 处理失败: {e}")
        if page:
            try:
                page.quit()
            except:
                pass
        return None


def analyze_all_profiles(profile_dirs: List[Path]) -> List[Dict[str, Any]]:
    """
    分析所有 Profile，返回每个 Profile 的信息列表。
    """
    results: List[Dict[str, Any]] = []
    
    print(f"\n{'='*60}")
    print(f"开始分析 {len(profile_dirs)} 个 Profile...")
    print(f"{'='*60}")
    
    for profile_dir in profile_dirs:
        email = get_email_from_preferences(profile_dir)
        sso = get_sso_from_profile(profile_dir)
        
        info = {
            "profile_path": str(profile_dir),
            "profile_name": profile_dir.name,
            "email": email,
            "sso": sso,
            "has_sso": sso is not None,
        }
        results.append(info)
    
    return results


def admin_login(username: str, password: str) -> str:
    """
    调用 /api/login，获取后台会话 token。
    """
    url = f"{BASE_URL}/api/login"
    resp = requests.post(url, json={"username": username, "password": password}, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    if not data.get("success"):
        raise RuntimeError(f"管理员登录失败: {data.get('message')}")

    token = data["token"]
    print("[OK] 管理员登录成功")
    return token


def add_tokens(tokens: List[str], session_token: str, token_type: str) -> None:
    """
    调用 /api/tokens/add 批量导入 token。
    """
    if not tokens:
        print("[INFO] 没有可导入的 Token")
        return

    url = f"{BASE_URL}/api/tokens/add"
    headers = {"Authorization": f"Bearer {session_token}"}
    payload = {
        "token_type": token_type,
        "tokens": tokens,
    }

    print(f"[INFO] 准备导入 {len(tokens)} 个 Token, 类型={token_type}")
    resp = requests.post(url, json=payload, headers=headers, timeout=60)
    print("[RESP]", resp.status_code, resp.text)


def main() -> None:
    # 1. 扫描所有 Profile_* 目录
    profile_dirs = iter_profile_dirs(PROFILE_ROOT)
    print(f"[INFO] 共发现 {len(profile_dirs)} 个 Profile_* 目录")

    # 2. 分析所有 Profile，获取账号信息和 sso
    profile_infos = analyze_all_profiles(profile_dirs)
    
    # 3. 统计信息
    print(f"\n{'='*60}")
    print("分析结果统计:")
    print(f"{'='*60}")
    
    with_email = [p for p in profile_infos if p["email"]]
    with_sso = [p for p in profile_infos if p["sso"]]
    
    print(f"  总 Profile 数: {len(profile_infos)}")
    print(f"  有邮箱信息: {len(with_email)} 个")
    if with_email:
        email_details = ', '.join([f"{p['profile_name']}({p['email']})" for p in with_email])
        print(f"    详情: {email_details}")
    print(f"  有 SSO Token: {len(with_sso)} 个")
    if with_sso:
        sso_details = ', '.join([p['profile_name'] for p in with_sso])
        print(f"    详情: {sso_details}")
    print()
    
    # 4. 显示详细结果
    print(f"{'='*60}")
    print("详细结果:")
    print(f"{'='*60}")
    for info in profile_infos:
        status = "✓" if info["has_sso"] else "✗"
        email_str = f" ({info['email']})" if info["email"] else ""
        print(f"  {status} {info['profile_name']}{email_str}")
    print()
    
    # 5. 提取所有有效的 sso tokens
    tokens: List[str] = []
    for info in profile_infos:
        if info["sso"]:
            tokens.append(info["sso"])
    
    # 去重
    tokens = list(dict.fromkeys(tokens))
    print(f"[INFO] 最终有效 sso 数量: {len(tokens)}")

    if not tokens:
        print("[WARN] 未获取到任何 sso，请先确认每个 Profile 已在浏览器中登录 Grok")
        return

    # 6. 询问是否导入
    print(f"\n准备导入 {len(tokens)} 个 SSO Token 到 grok2api...")
    confirm = input("是否继续导入? (y/n): ").strip().lower()
    if confirm != 'y':
        print("已取消导入")
        return

    # 7. 管理员登录 grok2api
    session_token = admin_login(ADMIN_USERNAME, ADMIN_PASSWORD)

    # 8. 批量导入到 grok2api
    add_tokens(tokens, session_token, TOKEN_TYPE)
    
    print("\n[完成] 导入流程已结束")


if __name__ == "__main__":
    main()

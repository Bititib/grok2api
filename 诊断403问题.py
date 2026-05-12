"""
诊断 403 问题的工具
检查代理和 CF Clearance 配置是否正确
"""

import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

async def check_config():
    """检查配置"""
    from app.core.config import setting
    from app.core.proxy_pool import proxy_pool
    
    print("=" * 60)
    print("403 问题诊断工具")
    print("=" * 60)
    print()
    
    # 重新加载配置
    await setting.reload()
    
    # 检查代理配置
    print("1. 代理配置检查:")
    proxy_url = setting.grok_config.get("proxy_url", "")
    proxy_pool_url = setting.grok_config.get("proxy_pool_url", "")
    
    if proxy_url:
        print(f"   ✓ 已配置静态代理: {proxy_url}")
    else:
        print(f"   ✗ 未配置静态代理")
    
    if proxy_pool_url:
        print(f"   ✓ 已配置代理池: {proxy_pool_url}")
    else:
        print(f"   - 未配置代理池（使用静态代理）")
    
    # 检查代理池状态
    proxy_url_normalized = setting.grok_config.get("proxy_url", "")
    proxy_pool_url_config = setting.grok_config.get("proxy_pool_url", "")
    proxy_pool_interval = setting.grok_config.get("proxy_pool_interval", 300)
    
    proxy_pool.configure(proxy_url_normalized, proxy_pool_url_config, proxy_pool_interval)
    
    current_proxy = await setting.get_proxy_async("service")
    if current_proxy:
        print(f"   ✓ 当前使用的代理: {current_proxy}")
    else:
        print(f"   ✗ 未获取到代理（可能配置有问题）")
    
    print()
    
    # 检查 CF Clearance
    print("2. CF Clearance 配置检查:")
    cf_value = setting.grok_config.get("cf_clearance", "")
    if cf_value:
        if cf_value.startswith("cf_clearance="):
            print(f"   ✓ CF Clearance 已配置（包含前缀）")
            print(f"   值: {cf_value[:50]}...")
        else:
            print(f"   ✓ CF Clearance 已配置（仅值，系统会自动添加前缀）")
            print(f"   值: {cf_value[:50]}...")
        print(f"   完整长度: {len(cf_value)} 字符")
    else:
        print(f"   ✗ 未配置 CF Clearance")
    
    print()
    
    # 检查 Cookie 构建
    print("3. Cookie 构建检查:")
    # 模拟构建 Cookie（使用示例 token）
    test_token = "test_token_example"
    cf = setting.grok_config.get("cf_clearance", "")
    cookie = f"{test_token};{cf}" if cf else test_token
    print(f"   Cookie 格式: {cookie[:80]}...")
    
    print()
    
    # 诊断建议
    print("4. 诊断建议:")
    issues = []
    
    if not proxy_url and not proxy_pool_url:
        issues.append("未配置代理")
    
    if not cf_value:
        issues.append("未配置 CF Clearance")
    
    if not current_proxy:
        issues.append("代理未正确加载（可能代理服务器未运行）")
    
    if issues:
        print("   发现的问题:")
        for i, issue in enumerate(issues, 1):
            print(f"   {i}. {issue}")
        print()
        print("   建议:")
        if "未配置代理" in issues:
            print("   - 配置代理地址（proxy_url）")
        if "未配置 CF Clearance" in issues:
            print("   - 配置 CF Clearance 值")
        if "代理未正确加载" in issues:
            print("   - 检查代理服务器是否运行（如 Clash、V2Ray）")
            print("   - 确认代理地址和端口正确")
            print("   - 测试代理连接: curl --proxy socks5://127.0.0.1:7890 https://grok.com")
    else:
        print("   ✓ 配置看起来正常")
        print()
        print("   如果仍然 403，可能原因:")
        print("   1. CF Clearance 已过期（需要重新获取）")
        print("   2. 代理服务器无法访问 grok.com")
        print("   3. 代理 IP 也被 Cloudflare 拦截")
        print("   4. 需要重启服务使配置生效（如果直接编辑了配置文件）")
    
    print()
    print("=" * 60)
    print("如何获取最新的 CF Clearance:")
    print("=" * 60)
    print("1. 在浏览器中访问 https://grok.com")
    print("2. 按 F12 → Application → Cookies → https://grok.com")
    print("3. 找到 'cf_clearance' Cookie，复制其值")
    print("4. 通过管理后台更新（立即生效）")
    print("=" * 60)

if __name__ == "__main__":
    import asyncio
    try:
        asyncio.run(check_config())
    except Exception as e:
        print(f"诊断失败: {e}")
        import traceback
        traceback.print_exc()


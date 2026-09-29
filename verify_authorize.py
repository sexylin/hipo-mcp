"""在服务器上验证 MCP /authorize 是否正常渲染登录页（公网 redirect_uri 场景）。

用途：
  直接构造一个「client 未注册 + 公网 https redirect_uri」的授权请求，
  断言服务端返回 200 登录页（而不是 400 Client not registered）。
  这正是本次「hipo-mcp 日志持续 401 / 无法认证登录」的根因场景。

用法：
  python3 verify_authorize.py                       # 默认打本地 8003
  HIPO_MCP_URL=http://127.0.0.1:8003 python3 verify_authorize.py
"""
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

BASE = os.environ.get("HIPO_MCP_URL", "http://127.0.0.1:8003").rstrip("/")
REDIRECT = "https://hipowork.com/oauth/callback"


def get(path: str) -> tuple[int, str]:
    url = f"{BASE}{path}"
    # 200 页面的表单/标题在 <body> 里，前面有较长内联 CSS，
    # 这里取全文判定（只做字符串存在性检查，开销可忽略）
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            return r.status, r.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "ignore")
    except Exception as e:  # noqa: BLE001
        return 0, f"ERROR: {e}"


def main() -> int:
    state = uuid.uuid4().hex
    params = {
        "client_id": str(uuid.uuid4()),   # 故意未注册，模拟重启后内存丢失
        "redirect_uri": REDIRECT,          # 公网域名，非 localhost
        "response_type": "code",
        "state": state,
        "scope": "profile candidate:read candidate:write",
        "code_challenge": "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
        "code_challenge_method": "S256",
    }
    path = "/authorize?" + urllib.parse.urlencode(params)
    code, body = get(path)

    print(f"请求: GET {path[:110]}...")
    print(f"状态码: {code}")

    is_json_err = body.lstrip().startswith("{") and '"error"' in body
    # 登录页渲染在 <script> 里有动态表单，DOM 形态不固定，
    # 用更稳定的特征判定：页面标题 + 验证码登录语义
    has_login_form = (
        "<form" in body
        or ("HiPo Work 认证" in body and ("验证码" in body or "邮箱" in body))
    )

    print(f"返回 JSON 错误: {is_json_err}")
    if is_json_err:
        print(f"错误内容: {body[:300]}")
    print(f"返回登录页: {has_login_form}")
    if "Client not registered" in body or "unauthorized_client" in body:
        print("命中: Client not registered（本次故障根因）")

    print()
    if code == 200 and has_login_form:
        print("✅ PASS：公网 redirect_uri + 未注册 client 能正常渲染登录页")
        print("   （说明 client 自动恢复容错已生效，授权可继续走完）")
        return 0
    if code in (302, 303):
        print("✅ PASS：直接 302 跳转（登录/授权流程已推进）")
        return 0
    print(f"❌ FAIL：状态码 {code}，授权链路仍不通。把完整输出与 hipo-mcp 日志贴回。")
    return 1


if __name__ == "__main__":
    sys.exit(main())

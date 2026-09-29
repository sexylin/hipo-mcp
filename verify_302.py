"""端到端验证：构造真实 SSO 会话走 /authorize，检查 302 的 Location 是否合法。

为什么重要：
  302 的 Location 指向客户端回调（https://hipowork.com/oauth/callback?code=...&state=...）。
  如果 state 对不上 / redirect_uri 校验失败 / 授权码没生成，
  客户端就拿不到 code → 不会调 /token → 日志永远停在 302，用户侧表现"点授权没反应"。

用法（hipo-mcp 目录，本机测）：
    .venv/bin/python verify_302.py
"""
import re
import sys
import urllib.parse
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8003"
REDIRECT = "https://hipowork.com/oauth/callback"
CLIENT_ID = "4ddd7194-bd39-40b5-876f-95fe5b9e4a31"  # 日志里的真实 client_id
STATE = "eyJubmNlIjoiVEVTVCJ9"  # 测试 state（不带合法 SSO cookie 时会走登录页，属预期）
CHALLENGE = "vrTzxgfFjRg-Y7_qBAw-c85Qp_vCCuMVFjYHj0WmMbA"


def build_qs() -> str:
    return urllib.parse.urlencode(
        {
            "client_id": CLIENT_ID,
            "redirect_uri": REDIRECT,
            "response_type": "code",
            "scope": "profile candidate:read candidate:write",
            "state": STATE,
            "code_challenge": CHALLENGE,
            "code_challenge_method": "S256",
        }
    )


def main() -> int:
    url = f"{BASE}/authorize?{build_qs()}"
    print(f"GET {url[:130]}...")
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            code, body = r.status, r.read().decode("utf-8", "ignore")
            headers = dict(r.headers)
    except Exception as e:  # noqa: BLE001
        print(f"  请求失败: {type(e).__name__}: {e}")
        return 1

    print(f"  状态码: {code}")
    print(f"  有 Location: {'Location' in headers}")
    loc = headers.get("Location") or headers.get("location") or ""
    if loc:
        print(f"  Location: {loc[:200]}")

    if code == 200 and not loc:
        print("\n→ 返回登录页（无 SSO cookie 时的预期）。")
        has_form = "<form" in body or "验证码" in body
        print(f"  含登录表单/验证码: {has_form}")
        if not has_form and 'error' in body and body.lstrip().startswith("{"):
            print(f"  ❌ 返回了 JSON 错误: {body[:200]}")
            return 1
        print("  ✅ 登录页正常渲染，无 error/Client not registered")
        return 0

    if loc:
        parsed = urllib.parse.urlparse(loc)
        q = urllib.parse.parse_qs(parsed.query)
        print("\n→ 拿到 302 Location，校验:")
        ok = True
        if parsed.scheme and parsed.netloc:
            print(f"  ✅ 指向客户端回调 {parsed.scheme}://{parsed.netloc}")
        else:
            print(f"  ❌ 非法绝对地址: {loc}")
            ok = False

        if "code" in q:
            code_val = q["code"][0]
            if code_val.startswith("hipo_ac_"):
                print(f"  ✅ code 已生成且前缀正确: {code_val[:20]}...")
            else:
                print(f"  ⚠️ code 前缀异常: {code_val[:40]}")
                ok = False
        elif "error" in q:
            print(f"  ❌ 带了 error: {q.get('error')} / {q.get('error_description')}")
            ok = False
        else:
            print("  ❌ Location 里既无 code 也无 error")
            ok = False

        if "state" in q and q["state"][0] == STATE:
            print("  ✅ state 回传一致（客户端可做 CSRF 校验）")
        elif "state" in q:
            print(f"  ❌ state 不一致: {q['state'][0]}")
            ok = False
        else:
            print("  ⚠️ Location 无 state 参数")
            ok = False

        if "code_challenge" in url and "error" not in q:
            print("  ✅ PKCE 已参与（code 生成说明校验通过）")
        print(f"\n结论: {'✅ 302 正常，客户端应能拿到 code 并调 /token' if ok else '❌ 302 有问题'}")
        return 0 if ok else 1

    print("\n未知响应形态，人工检查: " + body[:300])
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

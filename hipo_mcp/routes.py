"""HiPo OAuth 路由：登录页 + authorize + token"""

import json
import time
import os
import httpx
from collections import defaultdict

from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, JSONResponse

BACKEND_URL = os.environ.get("HIPO_BACKEND_URL", "http://127.0.0.1:8000")
API_BASE = f"{BACKEND_URL}/api/v1"
MCP_INTERNAL_SECRET = os.environ.get("MCP_INTERNAL_SECRET", "")

# MCP 层限流桶：IP → [timestamp]
_send_code_bucket: dict[str, list] = defaultdict(list)


# ══════════════════════════════════════════
# 登录页
# ══════════════════════════════════════════

LOGIN_PAGE_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>HiPo Work · 授权登录</title>
<style>
* { margin:0; padding:0; box-sizing:border-box; }
:root {
  --brand:#6366f1; --brand2:#8b5cf6; --accent:#22d3ee;
  --bg:#0b0d17; --card:rgba(20,22,38,.86);
  --border:rgba(255,255,255,.09); --border-hover:rgba(255,255,255,.2);
  --text:#e8eaf2; --dim:#9aa1b8; --radius:20px;
}
html,body{height:100%;}
body{
  font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei","Helvetica Neue",Arial,sans-serif;
  background:var(--bg); min-height:100vh; display:flex; align-items:center; justify-content:center;
  color:var(--text); overflow:hidden; position:relative;
}
body::before{ content:""; position:fixed; inset:0; z-index:0;
  background:
    radial-gradient(620px 420px at 12% 18%, rgba(99,102,241,.26), transparent 62%),
    radial-gradient(720px 520px at 88% 82%, rgba(139,92,246,.20), transparent 62%),
    radial-gradient(480px 380px at 72% 8%, rgba(34,211,238,.10), transparent 60%); }
body::after{ content:""; position:fixed; inset:0; z-index:0; opacity:.45;
  background-image:linear-gradient(rgba(255,255,255,.035) 1px,transparent 1px),
                   linear-gradient(90deg,rgba(255,255,255,.035) 1px,transparent 1px);
  background-size:46px 46px;
  -webkit-mask-image:radial-gradient(circle at 50% 50%,#000,transparent 78%);
  mask-image:radial-gradient(circle at 50% 50%,#000,transparent 78%); }
.wrap{ position:relative; z-index:1; width:100%; max-width:404px; padding:24px; }
.card{ background:var(--card); border:1px solid var(--border); border-radius:var(--radius);
  padding:40px 36px 34px;
  box-shadow:0 28px 90px rgba(0,0,0,.55), inset 0 1px 0 rgba(255,255,255,.07);
  -webkit-backdrop-filter:blur(22px); backdrop-filter:blur(22px); }
.brand{ display:flex; align-items:center; gap:12px; margin-bottom:26px; }
.logo{ width:44px; height:44px; border-radius:13px; flex:none; position:relative;
  background:linear-gradient(135deg,var(--brand),var(--brand2));
  box-shadow:0 8px 24px rgba(99,102,241,.45), inset 0 1px 0 rgba(255,255,255,.3);
  display:flex; align-items:center; justify-content:center; }
.logo svg{ width:24px; height:24px; }
.brand h1{ font-size:20px; font-weight:700; letter-spacing:.2px; }
.brand p{ font-size:13px; color:var(--dim); margin-top:2px; }
.head{ margin-bottom:26px; }
.head h2{ font-size:22px; font-weight:700; letter-spacing:.2px; }
.head p{ font-size:13.5px; color:var(--dim); margin-top:8px; line-height:1.6; }
.field{ position:relative; margin-bottom:20px; }
.field label{ display:block; font-size:13px; font-weight:600; color:var(--dim); margin-bottom:8px; letter-spacing:.2px; }
.field .in-wrap{ position:relative; }
.field svg.lead{ position:absolute; left:14px; top:50%; transform:translateY(-50%);
  width:18px; height:18px; color:var(--dim); pointer-events:none; }
.field input{ width:100%; padding:13px 14px 13px 42px; border:1px solid var(--border);
  border-radius:12px; font-size:15px; color:var(--text); outline:none;
  background:rgba(255,255,255,.045); transition:border-color .2s, box-shadow .2s, background .2s; }
.field input::placeholder{ color:rgba(154,161,184,.55); }
.field input:focus{ border-color:var(--brand); background:rgba(255,255,255,.06);
  box-shadow:0 0 0 4px rgba(99,102,241,.22); }
.btn{ width:100%; padding:14px; border:none; border-radius:12px; cursor:pointer;
  font-size:15px; font-weight:700; color:#fff; letter-spacing:.4px;
  background:linear-gradient(135deg,var(--brand),var(--brand2));
  box-shadow:0 10px 30px rgba(99,102,241,.35), inset 0 1px 0 rgba(255,255,255,.22);
  transition:transform .15s, box-shadow .2s, filter .2s; }
.btn:hover{ transform:translateY(-1px); filter:brightness(1.06);
  box-shadow:0 14px 36px rgba(99,102,241,.45), inset 0 1px 0 rgba(255,255,255,.25); }
.btn:active{ transform:translateY(0); }
.msg{ font-size:13px; border-radius:12px; padding:11px 14px; margin-bottom:18px; line-height:1.5; }
.msg.err{ background:rgba(244,63,94,.12); color:#fda4af; border:1px solid rgba(244,63,94,.25); }
.msg.ok{ background:rgba(16,185,129,.12); color:#6ee7b7; border:1px solid rgba(16,185,129,.25); }
.foot{ display:flex; align-items:center; justify-content:center; gap:7px;
  margin-top:24px; font-size:12px; color:var(--dim); }
.foot svg{ width:13px; height:13px; }
</style>
</head>
<body>
<div class="wrap">
  <div class="card">
    <div class="brand">
      <div class="logo">
        <svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l8 4.5v9L12 21l-8-4.5v-9L12 3z"/><path d="M12 12l8-4.5M12 12v9M12 12L4 7.5"/></svg>
      </div>
      <div><h1>HiPo Work</h1><p>AI 招聘平台</p></div>
    </div>
    <div class="head">
      <h2>授权连接你的 AI 助手</h2>
      <p>通过邮箱验证码登录，安全连接 MCP 服务，让你的 Agent 替你处理招聘与求职。</p>
    </div>
    {message}
    <form method="POST" action="/authorize">
      <input type="hidden" name="client_id" value="{client_id}">
      <input type="hidden" name="redirect_uri" value="{redirect_uri}">
      <input type="hidden" name="response_type" value="code">
      <input type="hidden" name="state" value="{state}">
      <input type="hidden" name="scope" value="{scope}">
      <input type="hidden" name="resource" value="{resource}">
      <input type="hidden" name="code_challenge" value="{code_challenge}">
      <input type="hidden" name="code_challenge_method" value="{code_challenge_method}">
      <input type="hidden" name="step" value="send_code">
      <div class="field">
        <label for="email">邮箱地址</label>
        <div class="in-wrap">
          <svg class="lead" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="4" width="20" height="16" rx="3"/><path d="M2 7l10 6 10-6"/></svg>
          <input id="email" type="email" name="email" placeholder="you@example.com" value="{email}" autocomplete="email" required>
        </div>
      </div>
      <button type="submit" class="btn">获取验证码</button>
    </form>
    <div class="foot">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0110 0v4"/></svg>
      通过邮箱验证码安全连接
    </div>
  </div>
</div>
</body>
</html>
"""

CODE_PAGE_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>HiPo Work · 输入验证码</title>
<style>
* { margin:0; padding:0; box-sizing:border-box; }
:root {
  --brand:#6366f1; --brand2:#8b5cf6; --accent:#22d3ee;
  --bg:#0b0d17; --card:rgba(20,22,38,.86);
  --border:rgba(255,255,255,.09); --border-hover:rgba(255,255,255,.2);
  --text:#e8eaf2; --dim:#9aa1b8; --radius:20px;
}
html,body{height:100%;}
body{
  font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei","Helvetica Neue",Arial,sans-serif;
  background:var(--bg); min-height:100vh; display:flex; align-items:center; justify-content:center;
  color:var(--text); overflow:hidden; position:relative;
}
body::before{ content:""; position:fixed; inset:0; z-index:0;
  background:
    radial-gradient(620px 420px at 12% 18%, rgba(99,102,241,.26), transparent 62%),
    radial-gradient(720px 520px at 88% 82%, rgba(139,92,246,.20), transparent 62%),
    radial-gradient(480px 380px at 72% 8%, rgba(34,211,238,.10), transparent 60%); }
body::after{ content:""; position:fixed; inset:0; z-index:0; opacity:.45;
  background-image:linear-gradient(rgba(255,255,255,.035) 1px,transparent 1px),
                   linear-gradient(90deg,rgba(255,255,255,.035) 1px,transparent 1px);
  background-size:46px 46px;
  -webkit-mask-image:radial-gradient(circle at 50% 50%,#000,transparent 78%);
  mask-image:radial-gradient(circle at 50% 50%,#000,transparent 78%); }
.wrap{ position:relative; z-index:1; width:100%; max-width:404px; padding:24px; }
.card{ background:var(--card); border:1px solid var(--border); border-radius:var(--radius);
  padding:40px 36px 34px;
  box-shadow:0 28px 90px rgba(0,0,0,.55), inset 0 1px 0 rgba(255,255,255,.07);
  -webkit-backdrop-filter:blur(22px); backdrop-filter:blur(22px); }
.brand{ display:flex; align-items:center; gap:12px; margin-bottom:26px; }
.logo{ width:44px; height:44px; border-radius:13px; flex:none; position:relative;
  background:linear-gradient(135deg,var(--brand),var(--brand2));
  box-shadow:0 8px 24px rgba(99,102,241,.45), inset 0 1px 0 rgba(255,255,255,.3);
  display:flex; align-items:center; justify-content:center; }
.logo svg{ width:24px; height:24px; }
.brand h1{ font-size:20px; font-weight:700; letter-spacing:.2px; }
.brand p{ font-size:13px; color:var(--dim); margin-top:2px; }
.head{ margin-bottom:26px; }
.head h2{ font-size:22px; font-weight:700; letter-spacing:.2px; }
.head .sent{ display:flex; align-items:center; gap:8px; margin-top:10px;
  font-size:13.5px; color:var(--dim); line-height:1.6; }
.head .sent svg{ width:16px; height:16px; flex:none; color:#6ee7b7; }
.head .sent b{ color:var(--text); font-weight:600; word-break:break-all; }
.otp{ position:relative; margin-bottom:22px; text-align:center; }
.otp input{ width:100%; padding:16px; border:1px solid var(--border);
  border-radius:14px; font-size:30px; font-weight:700; letter-spacing:16px; text-indent:16px;
  text-align:center; color:var(--text); outline:none;
  background:rgba(255,255,255,.05);
  transition:border-color .2s, box-shadow .2s, background .2s; font-variant-numeric:tabular-nums; }
.otp input::placeholder{ color:rgba(154,161,184,.3); font-weight:400; letter-spacing:14px; text-indent:14px; }
.otp input:focus{ border-color:var(--brand); background:rgba(255,255,255,.07);
  box-shadow:0 0 0 4px rgba(99,102,241,.22); }
.btn{ width:100%; padding:14px; border:none; border-radius:12px; cursor:pointer;
  font-size:15px; font-weight:700; color:#fff; letter-spacing:.4px;
  background:linear-gradient(135deg,var(--brand),var(--brand2));
  box-shadow:0 10px 30px rgba(99,102,241,.35), inset 0 1px 0 rgba(255,255,255,.22);
  transition:transform .15s, box-shadow .2s, filter .2s; }
.btn:hover{ transform:translateY(-1px); filter:brightness(1.06);
  box-shadow:0 14px 36px rgba(99,102,241,.45), inset 0 1px 0 rgba(255,255,255,.25); }
.btn:active{ transform:translateY(0); }
.msg{ font-size:13px; border-radius:12px; padding:11px 14px; margin-bottom:18px; line-height:1.5; }
.msg.err{ background:rgba(244,63,94,.12); color:#fda4af; border:1px solid rgba(244,63,94,.25); }
.msg.ok{ background:rgba(16,185,129,.12); color:#6ee7b7; border:1px solid rgba(16,185,129,.25); }
.back{ display:flex; align-items:center; justify-content:center; gap:6px;
  margin-top:22px; font-size:13px; color:var(--dim); }
.back a{ color:var(--brand); text-decoration:none; font-weight:600;
  transition:color .2s; }
.back a:hover{ color:var(--brand2); text-decoration:underline; }
</style>
</head>
<body>
<div class="wrap">
  <div class="card">
    <div class="brand">
      <div class="logo">
        <svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l8 4.5v9L12 21l-8-4.5v-9L12 3z"/><path d="M12 12l8-4.5M12 12v9M12 12L4 7.5"/></svg>
      </div>
      <div><h1>HiPo Work</h1><p>AI 招聘平台</p></div>
    </div>
    <div class="head">
      <h2>输入验证码</h2>
      <div class="sent">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 2L11 13"/><path d="M22 2l-7 20-4-9-9-4 20-7z"/></svg>
        <span>验证码已发送至 <b>{email}</b></span>
      </div>
    </div>
    {message}
    <form method="POST" action="/authorize">
      <input type="hidden" name="client_id" value="{client_id}">
      <input type="hidden" name="redirect_uri" value="{redirect_uri}">
      <input type="hidden" name="response_type" value="code">
      <input type="hidden" name="state" value="{state}">
      <input type="hidden" name="scope" value="{scope}">
      <input type="hidden" name="resource" value="{resource}">
      <input type="hidden" name="code_challenge" value="{code_challenge}">
      <input type="hidden" name="code_challenge_method" value="{code_challenge_method}">
      <input type="hidden" name="step" value="verify">
      <input type="hidden" name="email" value="{email}">
      <input type="hidden" name="role" value="{role}">
      <div class="otp">
        <input type="text" name="code" placeholder="······" maxlength="6" inputmode="numeric" pattern="[0-9]*" autocomplete="one-time-code" autofocus required>
      </div>
      <button type="submit" class="btn">完成登录</button>
    </form>
    <div class="back">未收到？<a href="javascript:history.back()">返回重新获取</a></div>
  </div>
</div>
</body>
</html>
"""

ROLE_SELECT_PAGE_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>HiPo Work · 选择身份</title>
<style>
* { margin:0; padding:0; box-sizing:border-box; }
:root {
  --brand:#6366f1; --brand2:#8b5cf6; --accent:#22d3ee;
  --bg:#0b0d17; --card:rgba(20,22,38,.86);
  --border:rgba(255,255,255,.09); --border-hover:rgba(255,255,255,.22);
  --text:#e8eaf2; --dim:#9aa1b8; --radius:20px;
}
html,body{height:100%;}
body{
  font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei","Helvetica Neue",Arial,sans-serif;
  background:var(--bg); min-height:100vh; display:flex; align-items:center; justify-content:center;
  color:var(--text); overflow:hidden; position:relative;
}
body::before{ content:""; position:fixed; inset:0; z-index:0;
  background:
    radial-gradient(620px 420px at 12% 18%, rgba(99,102,241,.26), transparent 62%),
    radial-gradient(720px 520px at 88% 82%, rgba(139,92,246,.20), transparent 62%),
    radial-gradient(480px 380px at 72% 8%, rgba(34,211,238,.10), transparent 60%); }
body::after{ content:""; position:fixed; inset:0; z-index:0; opacity:.45;
  background-image:linear-gradient(rgba(255,255,255,.035) 1px,transparent 1px),
                   linear-gradient(90deg,rgba(255,255,255,.035) 1px,transparent 1px);
  background-size:46px 46px;
  -webkit-mask-image:radial-gradient(circle at 50% 50%,#000,transparent 78%);
  mask-image:radial-gradient(circle at 50% 50%,#000,transparent 78%); }
.wrap{ position:relative; z-index:1; width:100%; max-width:440px; padding:24px; }
.card{ background:var(--card); border:1px solid var(--border); border-radius:var(--radius);
  padding:38px 32px 30px;
  box-shadow:0 28px 90px rgba(0,0,0,.55), inset 0 1px 0 rgba(255,255,255,.07);
  -webkit-backdrop-filter:blur(22px); backdrop-filter:blur(22px); }
.brand{ display:flex; align-items:center; gap:12px; margin-bottom:24px; }
.logo{ width:44px; height:44px; border-radius:13px; flex:none; position:relative;
  background:linear-gradient(135deg,var(--brand),var(--brand2));
  box-shadow:0 8px 24px rgba(99,102,241,.45), inset 0 1px 0 rgba(255,255,255,.3);
  display:flex; align-items:center; justify-content:center; }
.logo svg{ width:24px; height:24px; }
.brand h1{ font-size:20px; font-weight:700; letter-spacing:.2px; }
.brand p{ font-size:13px; color:var(--dim); margin-top:2px; }
.head{ margin-bottom:24px; }
.head h2{ font-size:22px; font-weight:700; letter-spacing:.2px; }
.head p{ font-size:13.5px; color:var(--dim); margin-top:8px; line-height:1.6; }
.role{ display:block; width:100%; text-align:left; cursor:pointer;
  background:rgba(255,255,255,.045); border:1px solid var(--border);
  border-radius:16px; padding:20px 18px; margin-bottom:14px; color:var(--text);
  transition:border-color .2s, background .2s, transform .15s, box-shadow .2s; }
.role:hover{ border-color:var(--brand); background:rgba(99,102,241,.09);
  transform:translateY(-2px); box-shadow:0 12px 32px rgba(99,102,241,.18); }
.role:active{ transform:translateY(0); }
.role .row{ display:flex; align-items:center; gap:14px; }
.role .ico{ width:46px; height:46px; border-radius:13px; flex:none;
  display:flex; align-items:center; justify-content:center;
  background:rgba(99,102,241,.16); color:#a5b4fc; }
.role.alt .ico{ background:rgba(34,211,238,.12); color:#67e8f9; }
.role .ico svg{ width:24px; height:24px; }
.role .txt{ flex:1; min-width:0; }
.role .tt{ font-size:16px; font-weight:700; letter-spacing:.2px; }
.role .ds{ font-size:12.5px; color:var(--dim); margin-top:4px; line-height:1.5; }
.role .ar{ flex:none; color:var(--dim); transition:transform .2s, color .2s; }
.role:hover .ar{ color:var(--brand); transform:translateX(3px); }
.role .ar svg{ width:18px; height:18px; }
.foot{ text-align:center; font-size:12px; color:var(--dim); margin-top:22px; }
</style>
</head>
<body>
<div class="wrap">
  <div class="card">
    <div class="brand">
      <div class="logo">
        <svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l8 4.5v9L12 21l-8-4.5v-9L12 3z"/><path d="M12 12l8-4.5M12 12v9M12 12L4 7.5"/></svg>
      </div>
      <div><h1>HiPo Work</h1><p>AI 招聘平台</p></div>
    </div>
    <div class="head">
      <h2>选择你的身份</h2>
      <p>首次使用，请选择你的身份。不同身份将获得对应的 AI 能力与权限。</p>
    </div>
    <form method="POST" action="/authorize">
      <input type="hidden" name="client_id" value="{client_id}">
      <input type="hidden" name="redirect_uri" value="{redirect_uri}">
      <input type="hidden" name="response_type" value="code">
      <input type="hidden" name="state" value="{state}">
      <input type="hidden" name="scope" value="{scope}">
      <input type="hidden" name="resource" value="{resource}">
      <input type="hidden" name="code_challenge" value="{code_challenge}">
      <input type="hidden" name="code_challenge_method" value="{code_challenge_method}">
      <input type="hidden" name="step" value="role_select">
      <input type="hidden" name="email" value="{email}">
      <input type="hidden" name="role" value="candidate">
      <button type="submit" class="role">
        <div class="row">
          <div class="ico"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 00-3-3.87"/><path d="M16 3.13a4 4 0 010 7.75"/></svg></div>
          <div class="txt">
            <div class="tt">我是求职者</div>
            <div class="ds">由 AI 帮你导入简历、管理求职档案</div>
          </div>
          <div class="ar"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14"/><path d="M12 5l7 7-7 7"/></svg></div>
        </div>
      </button>
    </form>
    <form method="POST" action="/authorize">
      <input type="hidden" name="client_id" value="{client_id}">
      <input type="hidden" name="redirect_uri" value="{redirect_uri}">
      <input type="hidden" name="response_type" value="code">
      <input type="hidden" name="state" value="{state}">
      <input type="hidden" name="scope" value="{scope}">
      <input type="hidden" name="resource" value="{resource}">
      <input type="hidden" name="code_challenge" value="{code_challenge}">
      <input type="hidden" name="code_challenge_method" value="{code_challenge_method}">
      <input type="hidden" name="step" value="role_select">
      <input type="hidden" name="email" value="{email}">
      <input type="hidden" name="role" value="employer">
      <button type="submit" class="role alt">
        <div class="row">
          <div class="ico"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6"/><path d="M3 7h18a1 1 0 011 1v2a1 1 0 01-1 1H3a1 1 0 01-1-1V8a1 1 0 011-1z"/><path d="M12 7v3M8 4h8v3H8z"/></svg></div>
          <div class="txt">
            <div class="tt">我是招聘方</div>
            <div class="ds">由 AI 帮你发布岗位、匹配候选人</div>
          </div>
          <div class="ar"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14"/><path d="M12 5l7 7-7 7"/></svg></div>
        </div>
      </button>
    </form>
    <div class="foot">身份选择后可在个人资料中修改</div>
  </div>
</div>
</body>
</html>
"""


DONE_PAGE_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>HiPo Work · 准备就绪</title>
<style>
* { margin:0; padding:0; box-sizing:border-box; }
:root {
  --brand:#6366f1; --brand2:#8b5cf6; --accent:#22d3ee;
  --bg:#0b0d17; --card:rgba(20,22,38,.86);
  --border:rgba(255,255,255,.09); --border-hover:rgba(255,255,255,.22);
  --text:#e8eaf2; --dim:#9aa1b8; --radius:20px;
}
html,body{height:100%;}
body{
  font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei","Helvetica Neue",Arial,sans-serif;
  background:var(--bg); min-height:100vh; display:flex; align-items:center; justify-content:center;
  color:var(--text); overflow:hidden; position:relative;
}
body::before{ content:""; position:fixed; inset:0; z-index:0;
  background:
    radial-gradient(620px 420px at 12% 18%, rgba(99,102,241,.26), transparent 62%),
    radial-gradient(720px 520px at 88% 82%, rgba(139,92,246,.20), transparent 62%),
    radial-gradient(480px 380px at 72% 8%, rgba(34,211,238,.10), transparent 60%); }
body::after{ content:""; position:fixed; inset:0; z-index:0; opacity:.45;
  background-image:linear-gradient(rgba(255,255,255,.035) 1px,transparent 1px),
                   linear-gradient(90deg,rgba(255,255,255,.035) 1px,transparent 1px);
  background-size:46px 46px;
  -webkit-mask-image:radial-gradient(circle at 50% 50%,#000,transparent 78%);
  mask-image:radial-gradient(circle at 50% 50%,#000,transparent 78%); }
.wrap{ position:relative; z-index:1; width:100%; max-width:440px; padding:24px; }
.card{ background:var(--card); border:1px solid var(--border); border-radius:var(--radius);
  padding:38px 34px 30px;
  box-shadow:0 28px 90px rgba(0,0,0,.55), inset 0 1px 0 rgba(255,255,255,.07);
  -webkit-backdrop-filter:blur(22px); backdrop-filter:blur(22px); }
.brand{ display:flex; align-items:center; gap:12px; margin-bottom:24px; }
.logo{ width:44px; height:44px; border-radius:13px; flex:none; position:relative;
  background:linear-gradient(135deg,var(--brand),var(--brand2));
  box-shadow:0 8px 24px rgba(99,102,241,.45), inset 0 1px 0 rgba(255,255,255,.3);
  display:flex; align-items:center; justify-content:center; }
.logo svg{ width:24px; height:24px; }
.brand h1{ font-size:20px; font-weight:700; letter-spacing:.2px; }
.brand p{ font-size:13px; color:var(--dim); margin-top:2px; }
.ready{ display:flex; align-items:center; gap:14px; margin-bottom:24px;
  background:rgba(16,185,129,.10); border:1px solid rgba(16,185,129,.25);
  border-radius:16px; padding:16px 18px; }
.ready .badge{ width:40px; height:40px; border-radius:50%; flex:none;
  background:linear-gradient(135deg,#10b981,#059669);
  display:flex; align-items:center; justify-content:center;
  box-shadow:0 6px 18px rgba(16,185,129,.35); }
.ready .badge svg{ width:22px; height:22px; }
.ready h2{ font-size:17px; font-weight:700; }
.ready p{ font-size:13px; color:var(--dim); margin-top:3px; line-height:1.5; }
.guide{ margin-bottom:24px; }
.guide .t{ font-size:13px; font-weight:700; color:var(--dim); text-transform:uppercase;
  letter-spacing:1.2px; margin-bottom:14px; }
.guide .p{ font-size:15px; font-weight:700; margin-bottom:16px; color:#a5b4fc; }
.guide ul{ list-style:none; }
.guide li{ display:flex; align-items:center; gap:10px; padding:9px 0;
  font-size:13.5px; color:var(--text); line-height:1.5; }
.guide li .dot{ width:6px; height:6px; border-radius:50%; flex:none;
  background:linear-gradient(135deg,var(--brand),var(--brand2)); }
.btn{ width:100%; padding:14px; border:none; border-radius:12px; cursor:pointer;
  font-size:15px; font-weight:700; color:#fff; letter-spacing:.4px;
  background:linear-gradient(135deg,var(--brand),var(--brand2));
  box-shadow:0 10px 30px rgba(99,102,241,.35), inset 0 1px 0 rgba(255,255,255,.22);
  transition:transform .15s, box-shadow .2s, filter .2s; }
.btn:hover{ transform:translateY(-1px); filter:brightness(1.06);
  box-shadow:0 14px 36px rgba(99,102,241,.45), inset 0 1px 0 rgba(255,255,255,.25); }
.btn:active{ transform:translateY(0); }
.foot{ text-align:center; font-size:12px; color:var(--dim); margin-top:22px; }
</style>
</head>
<body>
<div class="wrap">
  <div class="card">
    <div class="brand">
      <div class="logo">
        <svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l8 4.5v9L12 21l-8-4.5v-9L12 3z"/><path d="M12 12l8-4.5M12 12v9M12 12L4 7.5"/></svg>
      </div>
      <div><h1>HiPo Work</h1><p>AI 招聘平台</p></div>
    </div>
    <div class="ready">
      <div class="badge">
        <svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6L9 17l-5-5"/></svg>
      </div>
      <div>
        <h2>身份已就绪 · {role_name}</h2>
        <p>接下来可以直接让 AI 帮你处理</p>
      </div>
    </div>
    <div class="guide">
      <div class="t">接下来你可以</div>
      <div class="p">{role_summary}</div>
      <ul>{guide_items}</ul>
    </div>
    <form method="POST" action="/authorize">
      <input type="hidden" name="client_id" value="{client_id}">
      <input type="hidden" name="redirect_uri" value="{redirect_uri}">
      <input type="hidden" name="response_type" value="code">
      <input type="hidden" name="state" value="{state}">
      <input type="hidden" name="scope" value="{scope}">
      <input type="hidden" name="resource" value="{resource}">
      <input type="hidden" name="code_challenge" value="{code_challenge}">
      <input type="hidden" name="code_challenge_method" value="{code_challenge_method}">
      <input type="hidden" name="step" value="finalize">
      <input type="hidden" name="email" value="{email}">
      <input type="hidden" name="role" value="{role}">
      <button type="submit" class="btn">完成授权</button>
    </form>
    <div class="foot">完成后自动返回客户端，无需重复授权</div>
  </div>
</div>
</body>
</html>
"""


def _login_page(**kwargs) -> HTMLResponse:
    return _render_page(LOGIN_PAGE_HTML, kwargs)


def _code_page(**kwargs) -> HTMLResponse:
    return _render_page(CODE_PAGE_HTML, kwargs)


def _role_select_page(**kwargs) -> HTMLResponse:
    return _render_page(ROLE_SELECT_PAGE_HTML, kwargs)


def _done_page(**kwargs) -> HTMLResponse:
    return _render_page(DONE_PAGE_HTML, kwargs, raw_keys=frozenset({"guide_items"}))


def _role_guide(role: str) -> dict:
    """按角色组装授权完成页的引导文案（简单直接，2 条步骤）。"""
    if role == "employer":
        return {
            "role_name": "招聘方",
            "role_summary": "让 AI 帮你发布岗位、匹配候选人",
            "guide_items": (
                '<li><span class="dot"></span><span>让 Agent 发布岗位、匹配合适的候选人</span></li>'
                '<li><span class="dot"></span><span>回到客户端，向 Agent 下达任务即可开始</span></li>'
            ),
        }
    return {
        "role_name": "求职者",
        "role_summary": "让 AI 帮你导入简历、管理求职档案",
        "guide_items": (
            '<li><span class="dot"></span><span>把简历发给 Agent，让它帮你导入求职档案</span></li>'
            '<li><span class="dot"></span><span>回到客户端，向 Agent 下达任务即可开始</span></li>'
        ),
    }


def _render_page(template: str, kwargs: dict, raw_keys=frozenset()) -> HTMLResponse:
    """渲染 OAuth 页面，统一把 message/error 转成新样式消息块。

    message 是"已构造的 HTML 片段"：内嵌的用户/后端文本在构造时已转义，
    这里不再整体二次转义，否则 <div class="msg err"> 会被转成纯文本。
    """
    import html as _html
    import re

    # 兼容旧调用：error=xxx 转成新样式错误块（文本转义，包裹不转义）
    if "error" in kwargs:
        err = kwargs.pop("error")
        kwargs["message"] = f'<div class="msg err">{_html.escape(str(err))}</div>'
    elif "message" in kwargs and kwargs.get("message"):
        msg = str(kwargs["message"])
        # 兼容旧调用：message 已是 <div class="error|success">...</div>
        m = re.match(r'^<div class="(?:msg )?(err|ok|error|success)">(.*)</div>$', msg, re.S)
        if m:
            css = "err" if m.group(1) in ("err", "error") else "ok"
            text = _html.escape(m.group(2))
            kwargs["message"] = f'<div class="msg {css}">{text}</div>'
        else:
            # 纯文本 message：转义后包成错误块
            kwargs["message"] = f'<div class="msg err">{_html.escape(msg)}</div>'

    rendered = template
    for k, v in kwargs.items():
        if k == "message" or k in raw_keys:
            rendered = rendered.replace("{" + k + "}", str(v or ""))
        else:
            rendered = rendered.replace("{" + k + "}", str(_html.escape(str(v or ""))))
    # 清理剩余未替换的占位符
    rendered = re.sub(r"\{[a-z_]+\}", "", rendered)
    return HTMLResponse(rendered)


async def _finalize_authorize(provider, client, state, redirect_uri, scope, resource, code_challenge):
    """构建 AuthorizationParams 并完成 OAuth 授权跳转。

    AuthorizeError 不是 Starlette HTTPException，若不捕获会冒泡成 500，
    统一转成 JSON 4xx 返回给浏览器。
    """
    from mcp.server.auth.provider import AuthorizationParams, AuthorizeError

    auth_params = AuthorizationParams(
        redirect_uri=redirect_uri,
        redirect_uri_provided_explicitly=True,
        scopes=scope.split() if scope else [],
        state=state,
        code_challenge=code_challenge,
        resource=resource or None,
    )
    try:
        redirect_url = await provider.authorize(client, auth_params)
    except AuthorizeError as exc:
        err_code, err_desc = exc.args if len(exc.args) == 2 else (str(exc), str(exc))
        return JSONResponse(
            {"error": err_code, "error_description": err_desc},
            status_code=400,
        )
    return RedirectResponse(redirect_url, status_code=302)


def login_page_route(provider):
    """GET /authorize → 渲染登录页"""
    async def handler(request: Request):
        # 从 query 或 form 获取参数
        params = request.query_params if request.method == "GET" else await request.form()
        client_id = params.get("client_id", "")
        redirect_uri = params.get("redirect_uri", "")
        state = params.get("state", "")
        scope = params.get("scope", "")
        code_challenge = params.get("code_challenge", "")
        code_challenge_method = params.get("code_challenge_method", "")
        email = params.get("email", "")
        role = params.get("role", "candidate")
        if role not in ("candidate", "employer"):
            role = "candidate"

        client = await provider.get_client(client_id) if client_id else None
        if (
            not client
            or not state
            or params.get("response_type") != "code"
            or not code_challenge
            or code_challenge_method != "S256"
        ):
            return JSONResponse(
                {
                    "error": "invalid_request",
                    "error_description": "Authorization Code with PKCE S256 is required",
                },
                status_code=400,
            )
        try:
            # redirect_uri 从 query 进来是 str；SDK 的 validate_redirect_uri 用
            # AnyUrl 对象成员比较，str 与 AnyUrl 永远不相等（pydantic 已知坑），
            # 因此必须显式转成 AnyUrl 再校验。
            from pydantic import AnyUrl

            _redirect_input = AnyUrl(redirect_uri) if redirect_uri else None
            registered_redirect_uri = client.validate_redirect_uri(_redirect_input)
        except Exception as exc:
            return JSONResponse(
                {"error": "invalid_request", "error_description": str(exc)},
                status_code=400,
            )
        redirect_uri = str(registered_redirect_uri)
        provider.store_pending_transaction(
            state,
            {
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "state": state,
                "scope": scope,
                "code_challenge": code_challenge,
                "code_challenge_method": code_challenge_method,
                "resource": params.get("resource", ""),
            },
        )

        return _login_page(
            client_id=client_id,
            redirect_uri=redirect_uri,
            state=state,
            scope=scope,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
            email=email,
            role=role,
            message="",
            resource=params.get("resource", ""),
        )

    return handler


def authorize_route(provider):
    """处理登录表单提交：发送验证码或校验验证码并生成授权码。"""
    async def handler(request: Request):
        form = await request.form()
        client_id = form.get("client_id", "")
        redirect_uri = form.get("redirect_uri", "")
        state = form.get("state", "")
        scope = form.get("scope", "")
        code_challenge = form.get("code_challenge", "")
        code_challenge_method = form.get("code_challenge_method", "")
        step = form.get("step", "send_code")
        resource = form.get("resource", "")
        response_type = form.get("response_type", "")
        email = form.get("email", "")
        role = form.get("role", "candidate")
        if role not in ("candidate", "employer"):
            role = "candidate"

        client = await provider.get_client(client_id)
        if not client:
            return JSONResponse(
                {"error": "unauthorized_client", "error_description": "Client not registered"},
                status_code=400,
            )

        if response_type != "code" or not state or not code_challenge or code_challenge_method != "S256":
            return JSONResponse(
                {
                    "error": "invalid_request",
                    "error_description": "Authorization Code with PKCE S256 is required",
                },
                status_code=400,
            )

        transaction = provider.get_pending_transaction(state)
        expected_transaction = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "state": state,
            "scope": scope,
            "code_challenge": code_challenge,
            "code_challenge_method": code_challenge_method,
            "resource": resource,
        }
        if not state or any(
            transaction.get(key) != value for key, value in expected_transaction.items()
        ):
            return JSONResponse(
                {
                    "error": "invalid_request",
                    "error_description": "Authorization transaction mismatch",
                },
                status_code=400,
            )

        page_context = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "state": state,
            "scope": scope,
            "resource": resource,
            "code_challenge": code_challenge,
            "code_challenge_method": code_challenge_method,
            "email": email,
            "role": role,
        }

        if step == "send_code":
            # MCP 层限流：防止批量轰炸验证码发送接口。
            client_ip = request.client.host if request.client else "unknown"
            now = time.time()
            _send_code_bucket[client_ip].append(now)
            _send_code_bucket[client_ip] = [
                timestamp for timestamp in _send_code_bucket[client_ip] if timestamp > now - 60
            ]
            if len(_send_code_bucket[client_ip]) > 5:
                return _login_page(**page_context, message="请求过于频繁，请稍后再试")

            try:
                async with httpx.AsyncClient(timeout=10.0) as hc:
                    resp = await hc.post(f"{API_BASE}/auth/send-code", json={"email": email})
                    if resp.status_code != 200:
                        detail = resp.json().get("detail", {})
                        msg = detail.get("message", "发送失败") if isinstance(detail, dict) else str(detail)
                        return _login_page(**page_context, message=f'<div class="error">{msg}</div>')

                return _code_page(**page_context, redirect_uri_q=redirect_uri)
            except Exception as exc:
                return _login_page(
                    **page_context,
                    message=f'<div class="error">发送失败：{str(exc)[:80]}</div>',
                )

        if step == "verify":
            code = form.get("code", "")
            try:
                async with httpx.AsyncClient(timeout=10.0) as hc:
                    resp = await hc.post(
                        f"{API_BASE}/auth/register-or-login",
                        json={"email": email, "code": code, "role": role},
                    )
                    if resp.status_code != 200:
                        detail = resp.json().get("detail", {})
                        msg = detail.get("message", "验证失败") if isinstance(detail, dict) else str(detail)
                        return _code_page(
                            **page_context,
                            redirect_uri_q=redirect_uri,
                            error=msg,
                        )
                    user_data = resp.json()
            except Exception as exc:
                return _code_page(
                    **page_context,
                    redirect_uri_q=redirect_uri,
                    error=f"登录失败：{str(exc)[:80]}",
                )

            # 只暂存已验证的用户身份；OAuth token 由 Backend 在兑换授权码时签发。
            user_id = user_data.get("user_id", "")
            verified_role = user_data.get("role", role) or "candidate"
            is_new_user = user_data.get("is_new_user", False)
            provider.store_pending_auth(state, {
                "user_id": user_id,
                "role": verified_role,
                "scopes": scope.split() if scope else ["profile"],
            })

            # 新用户：验证码通过后先选角色（求职者/招聘方），再继续授权。
            if is_new_user:
                return _role_select_page(
                    client_id=client_id,
                    redirect_uri=redirect_uri,
                    response_type="code",
                    state=state,
                    scope=scope,
                    resource=resource,
                    code_challenge=code_challenge,
                    code_challenge_method=code_challenge_method,
                    email=email,
                )

            return await _finalize_authorize(
                provider, client, state, redirect_uri, scope, resource, code_challenge
            )

        if step == "role_select":
            # 新用户选定角色：用内部密钥调用后端更新角色，然后完成授权。
            selected_role = form.get("role", "candidate")
            if selected_role not in ("candidate", "employer"):
                selected_role = "candidate"
            # 非破坏性读取：pending 记录必须保留到 authorize() 消费，
            # 否则 role_select 会把 transaction/user_id 提前 pop 掉，
            # 导致最终 authorize 时 "Authorization transaction mismatch"。
            pending = provider.peek_pending_auth(state)
            user_id = pending.get("user_id", "")
            if not user_id:
                return JSONResponse(
                    {"error": "invalid_request", "error_description": "授权会话已过期，请重新开始"},
                    status_code=400,
                )
            try:
                async with httpx.AsyncClient(timeout=10.0) as hc:
                    resp = await hc.put(
                        f"{API_BASE}/auth/me/role",
                        json={"user_id": user_id, "role": selected_role},
                        headers={"X-MCP-Internal-Secret": MCP_INTERNAL_SECRET},
                    )
                    if resp.status_code != 200:
                        detail = resp.json().get("detail", {})
                        msg = detail.get("message", "角色设置失败") if isinstance(detail, dict) else str(detail)
                        return _role_select_page(
                            client_id=client_id,
                            redirect_uri=redirect_uri,
                            response_type="code",
                            state=state,
                            scope=scope,
                            resource=resource,
                            code_challenge=code_challenge,
                            code_challenge_method=code_challenge_method,
                            email=email,
                        )
                    user_data = resp.json()
            except Exception as exc:
                return _role_select_page(
                    client_id=client_id,
                    redirect_uri=redirect_uri,
                    response_type="code",
                    state=state,
                    scope=scope,
                    resource=resource,
                    code_challenge=code_challenge,
                    code_challenge_method=code_challenge_method,
                    email=email,
                )

            provider.store_pending_auth(state, {
                "user_id": user_id,
                "role": user_data.get("role", selected_role),
                "scopes": scope.split() if scope else ["profile"],
            })
            # 方案A：角色选定后先展示"准备就绪"引导页，用户点"完成授权"才真正跳转回调
            guide = _role_guide(user_data.get("role", selected_role))
            return _done_page(
                client_id=client_id,
                redirect_uri=redirect_uri,
                response_type="code",
                state=state,
                scope=scope,
                resource=resource,
                code_challenge=code_challenge,
                code_challenge_method=code_challenge_method,
                email=email,
                role=user_data.get("role", selected_role),
                **guide,
            )

        if step == "finalize":
            # 用户在引导页点了"完成授权"：真正生成授权码并跳回客户端
            final_role = provider.peek_pending_auth(state).get("role", "candidate")
            if final_role not in ("candidate", "employer"):
                final_role = "candidate"
            return await _finalize_authorize(
                provider, client, state, redirect_uri, scope, resource, code_challenge
            )

        return JSONResponse({"error": "invalid_request"}, status_code=400)

    return handler

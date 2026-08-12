#!/usr/bin/env python3
import json, urllib.request, os, sys

TOKEN = os.environ["GH_TOKEN"]

body = (
  "v1.5.0（修补版）\n\n"
  "包含本次所有修复：\n"
  "- 通知悬浮弹窗区分「紧急 / 普通」模式：\n"
  "  - 普通聊天消息、来信回信、朋友圈动态 → 顶部横幅几秒后自动收回（等同微信普通消息）\n"
  "  - 视频邀请、陪伴邀请 → 保留全屏弹窗等待用户响应（等同微信来电）\n"
  "- 回复拼接字卡开关：打开设置面板时刷新 UI，点击后立即保存避免设置丢失\n"
  "- 其他基础修复：字卡滚动跳动、悬浮音乐播放器字段保护、后台保活昵称同步等"
)
payload = json.dumps({
  "tag_name": "v1.5.0",
  "name": "v1.5.0 - Love App",
  "body": body,
  "draft": False,
  "prerelease": False
}).encode("utf-8")

req = urllib.request.Request(
  "https://api.github.com/repos/qcqzz/chat/releases",
  data=payload,
  headers={
    "Authorization": f"token {TOKEN}",
    "Accept": "application/vnd.github+json",
    "Content-Type": "application/json"
  },
  method="POST"
)
try:
  with urllib.request.urlopen(req) as resp:
    data = json.loads(resp.read())
    print(f"RELEASE_CREATED ID={data.get('id')} TAG={data.get('tag_name')}")
    print(f"UPLOAD_URL={data.get('upload_url','').split('{')[0]}")
    sys.stdout.flush()
except urllib.error.HTTPError as e:
  print(f"HTTP {e.code}", file=sys.stderr)
  msg = e.read().decode("utf-8", errors="replace")
  print(msg[:1200], file=sys.stderr)
  sys.exit(1)

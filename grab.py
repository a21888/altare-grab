#!/usr/bin/env python3
"""Altare 免费服务器抢占脚本 —— 在 GitHub Actions 上定时运行。

逻辑：
1. 先查团队现有服务器，已有则直接退出（避免多开）。
2. 没有则按指定区域/配置发创建请求。
3. 创建成功或失败都写 GitHub Step Summary；可选 PushPlus 微信通知。
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid

API = os.environ.get("ALTARE_API", "https://console.altare.gg/api")
TEAM = os.environ.get("ALTARE_TEAM_ID", "b7c7ee88-2a44-4c15-9feb-a6368744d6ba")
TOKEN = os.environ.get("ALTARE_TOKEN", "").strip()
PASSWORD = os.environ.get("SSH_PASSWORD", "").strip()
NAME = os.environ.get("SERVER_NAME", "yg-ubuntu")
LOCATION = os.environ.get("LOCATION", "us-lax").strip() or "us-lax"
EGG_ID = int(os.environ.get("EGG_ID", "46"))
MEMORY_MB = int(os.environ.get("MEMORY_MB", "4096"))
DISK_MB = int(os.environ.get("DISK_MB", "40960"))
CPU_PERCENT = int(os.environ.get("CPU_PERCENT", "125"))


def log(msg):
    print(msg, flush=True)


def summary(md):
    log(md)
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(md + "\n")


def request(method, path, body=None, extra_headers=None, timeout=45):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method)
    req.add_header("Authorization", "Bearer " + TOKEN)
    req.add_header("Accept", "application/json")
    req.add_header("User-Agent", "altare-grab/1.0")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    for k, v in (extra_headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except Exception as exc:  # 网络层错误
        return 0, str(exc)


def parse_items(raw):
    try:
        data = json.loads(raw)
    except Exception:
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("items", "servers", "data"):
            value = data.get(key)
            if isinstance(value, list):
                return value
    return []


def pick(item, *keys):
    for key in keys:
        value = item.get(key)
        if value not in (None, ""):
            return value
    return None


def describe(items):
    lines = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = pick(item, "name", "identifier", "id")
        host = pick(item, "ip", "ipAddress", "ip_address", "host", "hostname", "node")
        port = pick(item, "port", "sshPort", "ssh_port")
        status = pick(item, "status", "state")
        lines.append(f"- `{name}` | host={host} | port={port} | status={status}")
    return "\n".join(lines) if lines else "- （无法解析条目字段）"


def notify(title, content):
    token = os.environ.get("PUSHPLUS_TOKEN", "").strip()
    if not token:
        return
    try:
        payload = json.dumps({"token": token, "title": title, "content": content}).encode()
        req = urllib.request.Request("https://www.pushplus.plus/send", data=payload, method="POST")
        req.add_header("Content-Type", "application/json")
        urllib.request.urlopen(req, timeout=15).read()
    except Exception as exc:
        log(f"PushPlus 推送失败：{exc}")


def main():
    if not TOKEN:
        summary("## ❌ 缺少 ALTARE_TOKEN")
        return 1
    if not PASSWORD:
        summary("## ❌ 缺少 SSH_PASSWORD")
        return 1

    log(f"目标：{LOCATION} / {MEMORY_MB} MiB / {CPU_PERCENT}% / {DISK_MB} MiB / egg={EGG_ID}")

    status, raw = request("GET", f"/tenants/{TEAM}/servers")
    log(f"GET servers -> HTTP {status}")
    if status != 200:
        summary(f"## ⚠️ 查询失败 HTTP {status}\n```\n{raw[:800]}\n```")
        return 0

    items = parse_items(raw)
    if items:
        summary("## ✅ 已有服务器，无需创建\n" + describe(items))
        log(json.dumps(items, ensure_ascii=False)[:2000])
        return 0

    body = {
        "name": NAME,
        "eggId": EGG_ID,
        "memoryMb": MEMORY_MB,
        "diskMb": DISK_MB,
        "cpuPercent": CPU_PERCENT,
        "location": LOCATION,
        "ssh": {"password": PASSWORD},
    }
    status, raw = request(
        "POST",
        f"/tenants/{TEAM}/servers",
        body,
        {"Idempotency-Key": str(uuid.uuid4()), "Origin": "https://console.altare.gg"},
    )
    log(f"POST create -> HTTP {status} {raw[:500]}")

    if status not in (200, 201, 202):
        if status == 503:
            title = "Altare 无容量（继续蹲）"
        elif status == 429:
            title = "Altare 限流（继续蹲）"
        elif status == 500:
            title = "Altare 面板繁忙（继续蹲）"
        else:
            title = f"创建失败 HTTP {status}"
        summary(f"## ⏳ {title}\n```\n{raw[:800]}\n```")
        return 0

    # 创建请求已受理，轮询等待实例出现在列表里
    final = []
    for attempt in range(18):
        time.sleep(10)
        status, raw = request("GET", f"/tenants/{TEAM}/servers")
        items = parse_items(raw)
        if items:
            final = items
            break
        log(f"等待实例上线…… {attempt + 1}/18")

    if final:
        md = "## 🎉 服务器创建成功\n" + describe(final) + "\n\n```json\n" + json.dumps(final, ensure_ascii=False, indent=2)[:3000] + "\n```"
        summary(md)
        notify("Altare 服务器已创建", describe(final))
    else:
        summary("## ⚠️ 创建请求已受理，但列表暂未返回实例（可能仍在部署）\n```\n" + raw[:800] + "\n```")
        notify("Altare 创建请求已受理", "实例尚未出现在列表中，请查看 Actions 日志。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

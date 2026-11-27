#!/usr/bin/env python3
"""Altare free-server grabber with inventory check and Feishu webhook."""
import json
import os
import time
import urllib.error
import urllib.request

TEAM_ID = os.environ.get("ALTARE_TEAM_ID", "").strip()
TOKEN = os.environ["ALTARE_TOKEN"].strip()
SSH_PASSWORD = os.environ["SSH_PASSWORD"].strip()
NAME = os.environ.get("ALTARE_NAME", "pao").strip()
LOCATION = os.environ.get("ALTARE_LOCATION", "sg-sgp").strip()
LOCATIONS_PATH = os.environ.get("ALTARE_LOCATIONS_PATH", "/locations").strip()
EGG_ID = int(os.environ.get("ALTARE_EGG_ID", "46"))
MEMORY_MB = int(os.environ.get("ALTARE_MEMORY_MB", "4096"))
CPU_PERCENT = int(os.environ.get("ALTARE_CPU_PERCENT", "125"))
DISK_MB = int(os.environ.get("ALTARE_DISK_MB", "40960"))
LOOP_SECONDS = int(os.environ.get("LOOP_SECONDS", "20400"))
INTERVAL = int(os.environ.get("INTERVAL_SECONDS", "15"))
FEISHU_WEBHOOK = os.environ.get("FEISHU_WEBHOOK", "").strip()
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "").strip()
GH_PAT = os.environ.get("GH_PAT", "").strip()
GH_REPO = os.environ.get("GITHUB_REPOSITORY", "").strip()
GH_WORKFLOW = os.environ.get("GH_WORKFLOW_FILE", "grab.yml").strip()

BASE = "https://console.altare.gg/api"
HEADERS = {
    "Authorization": "Bearer " + TOKEN,
    "Accept": "application/json",
    "User-Agent": "altare-grab/1.1",
}


def log(msg):
    print(msg, flush=True)


def summary(msg):
    log(msg)
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        try:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(msg + "\n")
        except OSError:
            pass


def api(method, path, body=None, timeout=45):
    data = None
    headers = dict(HEADERS)
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
            try:
                return resp.status, json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                return resp.status, raw
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            return exc.code, raw
    except Exception as exc:
        return 0, {"error": str(exc)}


def list_servers():
    status, data = api("GET", f"/tenants/{TEAM_ID}/servers")
    if status != 200:
        return None, status, data
    items = []
    if isinstance(data, dict):
        items = data.get("items") or data.get("servers") or data.get("data") or []
        if isinstance(items, dict):
            items = items.get("items") or []
    elif isinstance(data, list):
        items = data
    return items, status, data


def check_location_available():
    """Return (available_bool_or_None, note). None means endpoint unavailable."""
    if not LOCATIONS_PATH:
        return None, "skip"
    status, data = api("GET", LOCATIONS_PATH)
    if status != 200:
        return None, f"GET {LOCATIONS_PATH} -> HTTP {status}"
    items = data.get("items", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
    for item in items:
        if isinstance(item, dict) and item.get("slug") == LOCATION:
            paused = item.get("creationPaused", False)
            return (not paused), f"slug={LOCATION} creationPaused={paused}"
    return None, f"slug={LOCATION} not found in {LOCATIONS_PATH}"


def extract_net(obj):
    found = {}

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                low = key.lower()
                if low in ("ip", "ipaddress", "ip_address", "address") and isinstance(value, str) and value and "ip" not in found:
                    found["ip"] = value
                if low in ("port", "portnumber") and isinstance(value, (int, str)) and "port" not in found:
                    found["port"] = value
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(obj)
    return found


def send_feishu(title, content):
    if not FEISHU_WEBHOOK:
        return
    payload = json.dumps({
        "msg_type": "text",
        "content": {"text": f"{title}\n{content}"},
    }).encode("utf-8")
    req = urllib.request.Request(
        FEISHU_WEBHOOK,
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            log(f"feishu -> HTTP {resp.status}")
    except Exception as exc:
        log(f"feishu failed: {exc}")


def send_pushplus(title, content):
    if not PUSHPLUS_TOKEN:
        return
    payload = json.dumps({
        "token": PUSHPLUS_TOKEN,
        "title": title,
        "content": content,
        "template": "txt",
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://www.pushplus.plus/send",
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "altare-grab/1.1"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            log(f"pushplus -> HTTP {resp.status}")
    except Exception as exc:
        log(f"pushplus failed: {exc}")


def notify(title, content):
    send_feishu(title, content)
    send_pushplus(title, content)


def trigger_next():
    if not GH_PAT or not GH_REPO:
        log("next run not triggered: GH_PAT or repo missing")
        return False
    url = f"https://api.github.com/repos/{GH_REPO}/actions/workflows/{GH_WORKFLOW}/dispatches"
    payload = json.dumps({"ref": "main"}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={
            "Authorization": "Bearer " + GH_PAT,
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "altare-grab/1.1",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            log(f"next run triggered -> HTTP {resp.status}")
            return True
    except Exception as exc:
        log(f"next run trigger failed: {exc}")
        return False


def main():
    if not TEAM_ID:
        summary("错误：ALTARE_TEAM_ID 为空，请先在仓库 Secrets 中配置。")
        return

    summary(f"目标：{LOCATION} / {MEMORY_MB} MiB / {CPU_PERCENT}% / {DISK_MB} MiB / egg={EGG_ID} / interval={INTERVAL}s")
    servers, status, _ = list_servers()
    if servers:
        names = ", ".join(str(s.get("name", s.get("id", "?"))) if isinstance(s, dict) else str(s) for s in servers)
        summary(f"已存在服务器：{names}，跳过创建。")
        return

    deadline = time.monotonic() + LOOP_SECONDS
    attempt = 0
    last_note = ""
    fallback_logged = False
    created = False
    server_info = None

    while time.monotonic() < deadline:
        attempt += 1

        avail, inv_note = check_location_available()
        if avail is False:
            if inv_note != last_note or attempt % 30 == 0:
                log(f"attempt={attempt} 暂无库存 ({inv_note})")
                last_note = inv_note
            time.sleep(INTERVAL)
            continue
        if avail is None and not fallback_logged:
            log(f"库存接口未命中 ({inv_note})，将直接轮询创建接口")
            fallback_logged = True
        elif avail is True:
            log(f"attempt={attempt} 检测到有库存 ({inv_note})，立即尝试创建")

        servers, status, _ = list_servers()
        if servers:
            created = True
            server_info = servers[0]
            summary(f"第 {attempt} 轮发现服务器已存在：{json.dumps(server_info, ensure_ascii=False)[:800]}")
            break
        if status not in (200, 0):
            log(f"attempt={attempt} GET servers -> HTTP {status}")

        body = {
            "name": NAME,
            "eggId": EGG_ID,
            "memoryMb": MEMORY_MB,
            "diskMb": DISK_MB,
            "cpuPercent": CPU_PERCENT,
            "location": LOCATION,
            "ssh": {"password": SSH_PASSWORD},
        }
        code, data = api("POST", f"/tenants/{TEAM_ID}/servers", body)
        note = json.dumps(data, ensure_ascii=False)[:200] if isinstance(data, (dict, list)) else str(data)[:200]

        if code in (200, 201):
            summary(f"第 {attempt} 轮创建成功：HTTP {code} {note}")
            created = True
            server_info = data
            time.sleep(10)
            servers, _, _ = list_servers()
            if servers:
                server_info = servers[0]
            break

        if note != last_note or attempt % 30 == 0:
            log(f"attempt={attempt} POST create -> HTTP {code} {note}")
            last_note = note

        wait = max(INTERVAL, 30) if code == 429 else INTERVAL
        time.sleep(wait)

    if created and server_info is not None:
        net = extract_net(server_info)
        detail = json.dumps(server_info, ensure_ascii=False)
        msg = (
            f"名称：{NAME}\n"
            f"位置：{LOCATION}\n"
            f"IP：{net.get('ip', '未解析')}\n"
            f"端口：{net.get('port', '未解析')}\n\n"
            f"{detail[:1200]}"
        )
        summary("服务器信息：" + detail[:1500])
        notify("Altare 服务器已创建", msg)
        summary("已创建成功，停止接力。")
        return

    summary(f"运行期满（{attempt} 次尝试）未抢到，触发下一轮。")
    trigger_next()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
import argparse
import json
import os
import socket
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

NGINX_CONF_PATH = Path("/etc/nginx/conf.d/default.conf")
STATUS_PATH = Path("/var/cache/failover/status.json")
FALLBACK_HTML_PATH = Path("/usr/share/nginx/html/fallback.html")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def html_escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#039;")
    )


def load_config() -> Dict[str, Any]:
    raw = os.getenv("FAILOVER_CONFIG_JSON", "").strip()
    config_file = os.getenv("FAILOVER_CONFIG_FILE", "").strip()

    if raw:
        cfg = json.loads(raw)
    elif config_file:
        cfg = json.loads(Path(config_file).read_text(encoding="utf-8"))
    else:
        raise RuntimeError("Debes definir FAILOVER_CONFIG_JSON o FAILOVER_CONFIG_FILE")

    if "targets" not in cfg or not isinstance(cfg["targets"], list) or not cfg["targets"]:
        raise RuntimeError("FAILOVER_CONFIG debe tener targets: [] con al menos un destino")

    cfg.setdefault("server_name", "_")
    cfg.setdefault("listen_port", 80)
    cfg.setdefault("routing_mode", "proxy")
    cfg.setdefault("check_interval_seconds", 5)
    cfg.setdefault("connect_timeout_seconds", 2)
    cfg.setdefault("read_timeout_seconds", 20)
    cfg.setdefault("fail_threshold", 2)
    cfg.setdefault("recover_threshold", 1)
    cfg.setdefault("fallback_title", "Servicio temporalmente no disponible")
    cfg.setdefault("fallback_message", "Estamos mostrando una página de respaldo mientras vuelve el servicio principal.")
    cfg.setdefault("fallback", {"type": "static", "name": "html-local"})

    routing_mode = str(cfg.get("routing_mode", "proxy")).lower().strip()
    if routing_mode not in ("proxy", "redirect"):
        raise RuntimeError("routing_mode debe ser proxy o redirect")
    cfg["routing_mode"] = routing_mode

    for idx, target in enumerate(cfg["targets"]):
        target.setdefault("name", f"target-{idx + 1}")
        target.setdefault("priority", idx + 1)
        target.setdefault("health_url", target.get("proxy_url"))
        target.setdefault("host_header", "")
        target.setdefault("routing_mode", routing_mode)
        if not target.get("proxy_url"):
            raise RuntimeError(f"Target {target['name']} no tiene proxy_url")
        if not target.get("health_url"):
            raise RuntimeError(f"Target {target['name']} no tiene health_url")

    fallback = cfg.get("fallback") or {"type": "static", "name": "html-local"}
    fallback.setdefault("type", "static")
    fallback.setdefault("name", "fallback")
    fallback.setdefault("host_header", "")
    fallback["type"] = str(fallback["type"]).lower().strip()
    if fallback["type"] not in ("static", "proxy", "redirect"):
        raise RuntimeError("fallback.type debe ser static, proxy o redirect")
    if fallback["type"] in ("proxy", "redirect") and not fallback.get("proxy_url"):
        raise RuntimeError("fallback.proxy_url es obligatorio cuando fallback.type es proxy o redirect")
    cfg["fallback"] = fallback

    cfg["targets"] = sorted(cfg["targets"], key=lambda t: int(t.get("priority", 9999)))
    return cfg


def write_fallback_html(cfg: Dict[str, Any]) -> None:
    title = html_escape(str(cfg.get("fallback_title", "Servicio temporalmente no disponible")))
    message = html_escape(str(cfg.get("fallback_message", "Estamos mostrando una página de respaldo mientras vuelve el servicio principal.")))
    html = f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{title}</title>
  <style>
    body {{
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
      font-family: Arial, Helvetica, sans-serif;
      background: #f5f5f5;
      color: #202020;
    }}
    main {{
      width: min(680px, calc(100% - 40px));
      background: white;
      border-radius: 18px;
      box-shadow: 0 12px 32px rgba(0,0,0,.10);
      padding: 34px;
      text-align: center;
    }}
    h1 {{ margin: 0 0 12px; font-size: 28px; }}
    p {{ margin: 0; line-height: 1.55; color: #555; }}
    small {{ display: block; margin-top: 24px; color: #888; }}
  </style>
</head>
<body>
  <main>
    <h1>{title}</h1>
    <p>{message}</p>
    <small>Fallback activo</small>
  </main>
</body>
</html>
"""
    FALLBACK_HTML_PATH.write_text(html, encoding="utf-8")


def check_target(target: Dict[str, Any], timeout: int) -> Tuple[bool, str, int]:
    url = target["health_url"]
    headers = {"User-Agent": "lkfailover/1.0"}
    if target.get("host_header"):
        headers["Host"] = str(target["host_header"])

    try:
        req = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            code = int(resp.status)
            ok = 200 <= code < 400
            return ok, f"HTTP {code}", code
    except urllib.error.HTTPError as e:
        code = int(e.code)
        return False, f"HTTP {code}", code
    except (urllib.error.URLError, TimeoutError, socket.timeout) as e:
        return False, str(e), 0
    except Exception as e:
        return False, str(e), 0


def render_proxy_location(destination: Dict[str, Any], cfg: Dict[str, Any], label: str) -> str:
    proxy_url = str(destination["proxy_url"]).rstrip("/")
    host_header = str(destination.get("host_header") or "$host")
    read_timeout = int(cfg["read_timeout_seconds"])
    connect_timeout = int(cfg["connect_timeout_seconds"])

    return f"""
  location / {{
    proxy_pass {proxy_url};
    proxy_http_version 1.1;

    proxy_set_header Host {host_header};
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $connection_upgrade;

    proxy_connect_timeout {connect_timeout}s;
    proxy_send_timeout {read_timeout}s;
    proxy_read_timeout {read_timeout}s;

    add_header X-LKFailover-Active-Target "{label}" always;
  }}
"""


def render_redirect_location(destination: Dict[str, Any], label: str) -> str:
    proxy_url = str(destination["proxy_url"]).rstrip("/")
    return f"""
  location / {{
    add_header X-LKFailover-Active-Target "{label}" always;
    return 302 {proxy_url}$request_uri;
  }}
"""


def render_static_fallback_location() -> str:
    return """
  location / {
    root /usr/share/nginx/html;
    try_files /fallback.html =503;
    add_header X-LKFailover-Active-Target "fallback-static" always;
  }
"""


def render_nginx_config(cfg: Dict[str, Any], active_target: Optional[Dict[str, Any]]) -> str:
    listen_port = int(cfg["listen_port"])
    server_name = str(cfg["server_name"])

    common = f"""
map $http_upgrade $connection_upgrade {{
  default upgrade;
  '' close;
}}

server {{
  listen {listen_port};
  server_name {server_name};

  access_log /var/log/nginx/access.log;
  error_log  /var/log/nginx/error.log warn;

  location = /healthz {{
    default_type text/plain;
    return 200 "ok\\n";
  }}

  location = /__failover_status {{
    default_type application/json;
    alias {STATUS_PATH};
  }}
"""

    if active_target:
        label = str(active_target.get("name", "active"))
        mode = str(active_target.get("routing_mode") or cfg.get("routing_mode", "proxy")).lower()
        location = render_redirect_location(active_target, label) if mode == "redirect" else render_proxy_location(active_target, cfg, label)
        return common + location + "}\n"

    fallback = cfg.get("fallback") or {"type": "static", "name": "fallback-static"}
    fallback_type = str(fallback.get("type", "static")).lower()
    fallback_label = str(fallback.get("name", "fallback"))

    if fallback_type == "proxy":
        location = render_proxy_location(fallback, cfg, fallback_label)
    elif fallback_type == "redirect":
        location = render_redirect_location(fallback, fallback_label)
    else:
        location = render_static_fallback_location()

    return common + location + "}\n"


def safe_write_nginx_config(new_conf: str, reload_nginx: bool) -> bool:
    old_conf = NGINX_CONF_PATH.read_text(encoding="utf-8") if NGINX_CONF_PATH.exists() else ""
    if old_conf == new_conf:
        return False

    NGINX_CONF_PATH.write_text(new_conf, encoding="utf-8")
    test = subprocess.run(["nginx", "-t"], capture_output=True, text=True)

    if test.returncode != 0:
        NGINX_CONF_PATH.write_text(old_conf, encoding="utf-8")
        print("[watcher] nginx -t falló. Se restauró config anterior.")
        print(test.stderr)
        return False

    if reload_nginx:
        subprocess.run(["nginx", "-s", "reload"], check=False)
    return True


def write_status(cfg: Dict[str, Any], statuses: List[Dict[str, Any]], active_target: Optional[Dict[str, Any]]) -> None:
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    fallback = cfg.get("fallback") or {"type": "static", "name": "fallback-static"}
    active_name = active_target.get("name") if active_target else fallback.get("name", "fallback-static")
    payload = {
        "updated_at": now_iso(),
        "server_name": cfg.get("server_name"),
        "routing_mode": cfg.get("routing_mode"),
        "active_target": active_name,
        "fallback": fallback,
        "targets": statuses,
    }
    STATUS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def evaluate_targets(cfg: Dict[str, Any], memory: Dict[str, Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    statuses: List[Dict[str, Any]] = []

    fail_threshold = int(cfg["fail_threshold"])
    recover_threshold = int(cfg["recover_threshold"])
    timeout = int(cfg["connect_timeout_seconds"])

    for target in cfg["targets"]:
        name = target["name"]
        mem = memory.setdefault(name, {"healthy": False, "successes": 0, "fails": 0})
        ok, detail, code = check_target(target, timeout)

        if ok:
            mem["successes"] += 1
            mem["fails"] = 0
            if mem["successes"] >= recover_threshold:
                mem["healthy"] = True
        else:
            mem["fails"] += 1
            mem["successes"] = 0
            if mem["fails"] >= fail_threshold:
                mem["healthy"] = False

        statuses.append({
            "name": name,
            "priority": target.get("priority"),
            "proxy_url": target.get("proxy_url"),
            "health_url": target.get("health_url"),
            "host_header": target.get("host_header"),
            "healthy": bool(mem["healthy"]),
            "last_check_ok": bool(ok),
            "last_http_code": code,
            "detail": detail,
            "successes": mem["successes"],
            "fails": mem["fails"],
        })

    active = None
    for target in cfg["targets"]:
        if memory[target["name"]]["healthy"]:
            active = target
            break

    return statuses, active


def run_once(memory: Dict[str, Dict[str, Any]], reload_nginx: bool) -> None:
    cfg = load_config()
    write_fallback_html(cfg)
    statuses, active = evaluate_targets(cfg, memory)
    write_status(cfg, statuses, active)
    changed = safe_write_nginx_config(render_nginx_config(cfg, active), reload_nginx=reload_nginx)
    fallback = cfg.get("fallback") or {"name": "fallback-static"}
    active_name = active["name"] if active else fallback.get("name", "fallback-static")
    print(f"[watcher] {now_iso()} active={active_name} changed={changed}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--watch", action="store_true")
    args = parser.parse_args()

    memory: Dict[str, Dict[str, Any]] = {}

    if args.once:
        cfg = load_config()
        for target in cfg["targets"]:
            memory[target["name"]] = {"healthy": False, "successes": 0, "fails": 0}
        run_once(memory, reload_nginx=False)
        return

    if args.watch:
        while True:
            cfg = load_config()
            run_once(memory, reload_nginx=True)
            time.sleep(int(cfg["check_interval_seconds"]))
        return

    parser.print_help()


if __name__ == "__main__":
    main()

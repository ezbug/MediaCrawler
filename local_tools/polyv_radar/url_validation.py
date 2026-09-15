from __future__ import annotations

import ipaddress
import json
import socket
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from pathlib import Path


USER_AGENT = "POLYV-Radar-Link-Checker/1.0"
MAX_BODY_BYTES = 256 * 1024


def _blocked_host(host: str) -> bool:
    if not host:
        return True
    if host.casefold() in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        return True
    try:
        addresses = socket.getaddrinfo(host, None)
    except OSError:
        return False
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address[4][0])
        except (IndexError, ValueError):
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return True
    return False


def validate_url(url: str, timeout: float = 5.0) -> dict:
    checked_at = datetime.now(timezone.utc).isoformat()
    parsed = urlparse(str(url or "").strip())
    result = {
        "url": str(url or ""),
        "status": "invalid",
        "http_status": 0,
        "final_url": "",
        "reason": "",
        "checked_at": checked_at,
    }
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        result["reason"] = "仅支持 http/https 链接"
        return result
    if _blocked_host(parsed.hostname or ""):
        result["reason"] = "跳过本机或内网地址"
        return result
    request = Request(str(url), headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml,*/*"})
    try:
        with urlopen(request, timeout=timeout) as response:
            status_code = int(response.getcode() or 0)
            final_url = response.geturl() or str(url)
            body = response.read(MAX_BODY_BYTES)
        result.update({"http_status": status_code, "final_url": final_url})
        if 200 <= status_code < 400:
            result["status"] = "ok"
            result["reason"] = "页面可访问"
        else:
            result["status"] = "failed"
            result["reason"] = f"HTTP {status_code}"
        if body:
            result["body_bytes"] = len(body)
        return result
    except HTTPError as exc:
        result.update({"http_status": int(exc.code or 0), "final_url": exc.geturl() or str(url)})
        result["status"] = "not_found" if exc.code in {404, 410} else "blocked" if exc.code in {401, 403, 429} else "failed"
        result["reason"] = f"HTTP {exc.code}"
    except (TimeoutError, socket.timeout):
        result["status"] = "timeout"
        result["reason"] = "连接超时"
    except (URLError, OSError) as exc:
        result["status"] = "error"
        result["reason"] = str(getattr(exc, "reason", exc))[:240]
    return result


def validate_urls(urls: list[str], timeout: float = 5.0, max_workers: int = 4) -> dict[str, dict]:
    unique = sorted({str(url).strip() for url in urls if str(url).strip()})
    checked: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=max(1, min(max_workers, len(unique) or 1))) as pool:
        futures = {pool.submit(validate_url, url, timeout): url for url in unique}
        for future in as_completed(futures):
            url = futures[future]
            try:
                checked[url] = future.result()
            except Exception as exc:
                checked[url] = {
                    "url": url,
                    "status": "error",
                    "http_status": 0,
                    "final_url": "",
                    "reason": str(exc)[:240],
                    "checked_at": datetime.now(timezone.utc).isoformat(),
                }
    return {url: checked[url] for url in unique}


def validate_urls_with_ego(
    urls: list[str],
    repo_root: Path,
    work_dir: Path,
    runner=subprocess.run,
    timeout: int = 240,
) -> tuple[dict[str, dict], str]:
    unique = sorted({str(url).strip() for url in urls if str(url).strip()})[:200]
    if not unique:
        return {}, ""
    work_dir.mkdir(parents=True, exist_ok=True)
    input_path = work_dir / "url-check-input.json"
    output_path = work_dir / "url-check-output.json"
    input_path.write_text(json.dumps({"urls": unique}, ensure_ascii=False), encoding="utf-8")
    script_path = repo_root / "local_tools" / "polyv_radar" / "ego_url_validator.mjs"
    log = ""
    launcher = (
        f"process.env.POLYV_URL_INPUT = {json.dumps(str(input_path))};\n"
        f"process.env.POLYV_URL_OUTPUT = {json.dumps(str(output_path))};\n"
        f"await import({json.dumps(str(script_path))});\n"
    )
    try:
        result = runner(
            ["ego-browser", "nodejs"],
            input=launcher,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
            cwd=repo_root,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {url: {"url": url, "status": "error", "http_status": 0, "final_url": "", "reason": f"Ego Lite校验失败: {exc}", "checked_at": datetime.now(timezone.utc).isoformat()} for url in unique}, str(exc)
    if result.returncode != 0 or not output_path.exists():
        log = (result.stderr or result.stdout or "Ego Lite校验没有生成结果").strip()[-1000:]
        return {url: {"url": url, "status": "error", "http_status": 0, "final_url": "", "reason": f"Ego Lite校验失败: {log}", "checked_at": datetime.now(timezone.utc).isoformat()} for url in unique}, log
    try:
        payload = json.loads(output_path.read_text(encoding="utf-8"))
        results = payload.get("results", [])
        checked = {str(item.get("url", "")): item for item in results if item.get("url")}
    except (OSError, json.JSONDecodeError) as exc:
        checked = {}
        log = f"Ego Lite结果解析失败: {exc}"
    return {
        url: checked.get(url, {"url": url, "status": "error", "http_status": 0, "final_url": "", "reason": "Ego Lite未返回结果", "checked_at": datetime.now(timezone.utc).isoformat()})
        for url in unique
    }, log


def dump_url_checks(path, checks: dict[str, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(checks, ensure_ascii=False, indent=2), encoding="utf-8")

"""企业邮箱 URL 特征探针（研究用，只读）。

抓取企业官网首页与联系类页面，统计公开邮箱出现的 URL 路径模式，
用于设计“企业邮箱发现”抓取策略。只处理公开页面上已发布的邮箱，
不猜测、不拼接个人邮箱。

用法：
    uv run python -m local_tools.polyv_radar.email_url_probe --site youzan.com --site weimob.com
    uv run python -m local_tools.polyv_radar.email_url_probe  # 使用内置样例站点
"""
from __future__ import annotations

import argparse
import json
import re
import ssl
import urllib.parse
import urllib.request

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

DEFAULT_SITES = (
    "polyv.net",
    "youzan.com",
    "weimob.com",
    "xiaoe-tech.com",
    "vhall.com",
    "baijiayun.com",
    "mudu.tv",
    "yonyou.com",
    "kingdee.com",
    "neusoft.com",
    "haier.com",
    "midea.com",
)

LINK_KEYWORDS = (
    "contact", "contactus", "contact-us", "lianxi", "lxwm", "about", "aboutus",
    "about-us", "gywm", "join", "job", "hr", "careers", "zhaopin", "recruit",
    "ir", "investor", "tzzgx", "gonggao", "announcement", "news", "press",
)

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
HREF_RE = re.compile(r'href=["\']([^"\']+)["\']', re.I)
BAD_SUFFIX = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".css", ".js", ".ico")


def fetch(url: str, timeout: float = 10.0) -> tuple[str | None, str]:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            body = resp.read(800_000)
            return resp.geturl(), body.decode("utf-8", "ignore")
    except Exception as exc:  # noqa: BLE001 - 研究探针，保留错误文本
        return None, f"{type(exc).__name__}: {exc}"


def find_emails(html: str) -> list[str]:
    found = []
    for match in EMAIL_RE.findall(html):
        email = match.strip(".")
        if email.lower().endswith(BAD_SUFFIX):
            continue
        if email not in found:
            found.append(email)
    return found


def classify_path(path: str) -> str:
    low = path.lower()
    for key, label in (
        (("contact", "lianxi", "lxwm"), "contact"),
        (("about", "gywm"), "about"),
        (("join", "job", "hr", "career", "zhaopin", "recruit"), "jobs"),
        (("investor", "tzzgx", "/ir"), "ir"),
        (("gonggao", "announcement", "news", "press"), "news"),
    ):
        if any(token in low for token in key):
            return label
    return "other"


def probe_site(domain: str, max_pages: int = 5) -> dict:
    home_url = f"https://www.{domain}"
    final_url, html = fetch(home_url)
    result: dict = {"domain": domain, "home": {"url": final_url or home_url, "ok": bool(html and final_url)}}
    if not html:
        result["error"] = final_url or "fetch failed"
        return result

    pages = [{"url": final_url, "path": urllib.parse.urlparse(final_url or home_url).path or "/", "emails": find_emails(html)}]
    seen = {final_url}
    candidates: list[str] = []
    for href in HREF_RE.findall(html):
        absolute = urllib.parse.urljoin(final_url or home_url, href)
        parsed = urllib.parse.urlparse(absolute)
        if parsed.scheme not in ("http", "https") or parsed.netloc != urllib.parse.urlparse(final_url or home_url).netloc:
            continue
        if absolute in seen:
            continue
        low = (parsed.path + "?" + parsed.query).lower()
        if any(keyword in low for keyword in LINK_KEYWORDS):
            seen.add(absolute)
            candidates.append(absolute.split("#")[0])
        if len(candidates) >= max_pages * 2:
            break

    for url in candidates:
        if len(pages) >= max_pages + 1:
            break
        page_url, page_html = fetch(url)
        if not page_html:
            continue
        path = urllib.parse.urlparse(page_url or url).path or "/"
        emails = find_emails(page_html)
        pages.append({"url": page_url or url, "path": path, "kind": classify_path(path), "emails": emails})

    result["pages"] = pages
    emails_all: list[str] = []
    for page in pages:
        for email in page["emails"]:
            if email not in emails_all:
                emails_all.append(email)
    result["emails"] = emails_all
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="企业邮箱 URL 特征探针（只读研究）")
    parser.add_argument("--site", action="append", help="站点域名，可重复；省略时使用内置样例")
    parser.add_argument("--max-pages", type=int, default=5)
    parser.add_argument("--output", help="结果 JSON 落盘路径")
    args = parser.parse_args(argv)

    sites = args.site or list(DEFAULT_SITES)
    results = [probe_site(site, max_pages=args.max_pages) for site in sites]
    payload = json.dumps(results, ensure_ascii=False, indent=2)
    if args.output:
        from pathlib import Path

        Path(args.output).write_text(payload + "\n", encoding="utf-8")
        print(f"written: {args.output}")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

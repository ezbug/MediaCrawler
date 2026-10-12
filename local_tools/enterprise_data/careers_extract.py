"""企业官网招聘页抽取（官方来源优先，只读）。

优先解析 schema.org JobPosting 的 JSON-LD（结构化、稳定），
没有 JSON-LD 时回退到页面锚点里的职位标题，并识别“招 N 人”。
输出与 import-jobs 兼容的 JSON；JS 渲染页面会给出告警（改用 Ego Lite）。
"""
from __future__ import annotations

import hashlib
import json
import re
import ssl
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
CAREERS_KEYWORDS = ("career", "jobs", "job", "join", "joinus", "recruit", "talent", "zhaopin", "hr", "招聘", "加入我们")
ROLE_HINTS = (
    "工程师", "经理", "专员", "主管", "助理", "总监", "实习生", "架构师", "设计师", "研究员",
    "顾问", "讲师", "开发", "设计", "运营", "销售", "客服", "财务", "人事", "法务", "采购",
    "测试", "前端", "后端", "算法", "产品经理", "项目经理",
)
NAV_BLOCK = (
    "案例", "功能", "中心", "首页", "关于", "联系", "咨询", "更多", "详情", "查看", "了解", "方案",
    "申请", "投递", "登录", "注册", "宣讲", "商城", "文档", "开发者", "新闻", "活动", "介绍",
    "服务", "认证", "合作", "下载", "帮助", "试用", "免费", "学堂", "课程",
)
CAREERS_TEXT_PRIORITY = ("加入我们", "招贤纳士", "人才招聘", "社会招聘", "校园招聘", "职位", "careers", "join us")
CAREERS_HREF_PRIORITY = ("career", "jobs", "job", "zhaopin", "recruit", "join")
#: 国内常见的第三方招聘系统（ATS）：职位多由 JS 渲染，HTML 直采通常拿不到，需要 Ego Lite。
ATS_PROVIDERS = {
    "mokahr.com": "Moka",
    "zhiye.com": "北森",
    "beisen.com": "北森",
    "ctghr.com": "大易",
    "dayee.com": "大易",
    "zhipin.com": "BOSS直聘",
    "51job.com": "前程无忧",
    "zhaopin.com": "智联招聘",
    "liepin.com": "猎聘",
    "lagou.com": "拉勾",
}
HIRING_COUNT_PATTERN = re.compile(r"招(?:聘)?\s*(\d{1,4})\s*人")


class _Collector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.scripts: list[tuple[dict, str]] = []
        self.anchors: list[tuple[str, str]] = []
        self._in_script = False
        self._script_attrs: dict = {}
        self._script_parts: list[str] = []
        self._href: str | None = None
        self._anchor_parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script":
            self._in_script = True
            self._script_attrs = attrs
            self._script_parts = []
        elif tag == "a":
            self._href = attrs.get("href")
            self._anchor_parts = []

    def handle_data(self, data):
        if self._in_script:
            self._script_parts.append(data)
        if self._href is not None:
            self._anchor_parts.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self._in_script:
            self._in_script = False
            self.scripts.append((self._script_attrs, "".join(self._script_parts)))
        elif tag == "a" and self._href is not None:
            text = re.sub(r"\s+", " ", "".join(self._anchor_parts)).strip()
            if text:
                self.anchors.append((self._href, text))
            self._href = None


def fetch(url: str, timeout: float = 15.0) -> tuple[str | None, str]:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    request = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"})
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=ctx) as response:
            return response.geturl(), response.read(1_500_000).decode("utf-8", "ignore")
    except Exception as exc:  # noqa: BLE001 - 采集探针保留错误文本
        return None, f"{type(exc).__name__}: {exc}"


def parse_html(html: str) -> _Collector:
    collector = _Collector()
    collector.feed(html)
    collector.close()
    return collector


def _iter_json_nodes(payload):
    if isinstance(payload, list):
        for item in payload:
            yield from _iter_json_nodes(item)
    elif isinstance(payload, dict):
        if "@graph" in payload:
            yield from _iter_json_nodes(payload["@graph"])
        yield payload


def _location(node: dict) -> str:
    locations = node.get("jobLocation")
    if isinstance(locations, list):
        locations = locations[0] if locations else None
    if not isinstance(locations, dict):
        return ""
    address = locations.get("address") or {}
    if isinstance(address, list):
        address = address[0] if address else {}
    if not isinstance(address, dict):
        return ""
    return str(address.get("addressLocality") or address.get("addressRegion") or "").strip()


def _job_id(url: str, title: str) -> str:
    return hashlib.sha1(f"{url}|{title}".encode("utf-8")).hexdigest()[:16]


def json_ld_jobs(collector: _Collector, base_url: str) -> list[dict]:
    jobs = []
    for attrs, data in collector.scripts:
        if "ld+json" not in str(attrs.get("type") or "").lower():
            continue
        try:
            payload = json.loads(data.strip() or "null")
        except json.JSONDecodeError:
            continue
        for node in _iter_json_nodes(payload):
            if str(node.get("@type") or "").lower() != "jobposting":
                continue
            title = str(node.get("title") or "").strip()
            if not title:
                continue
            url = urllib.parse.urljoin(base_url, str(node.get("url") or ""))
            jobs.append({
                "platform": "careers",
                "platform_job_id": _job_id(url or base_url, title),
                "job_title": title,
                "job_url": url or base_url,
                "city": _location(node),
                "publish_date": str(node.get("datePosted") or "")[:10],
                "raw_hiring_text": "",
                "recruitment_count": None,
                "source_provider": "company_site",
                "extraction_method": "json-ld",
                "verification_status": "unverified",
            })
    return jobs


def anchor_jobs(collector: _Collector, base_url: str) -> list[dict]:
    jobs = []
    seen: set[str] = set()
    for href, text in collector.anchors:
        if len(text) > 24 or not any(hint in text for hint in ROLE_HINTS):
            continue
        if any(block in text for block in NAV_BLOCK):
            continue
        if not href or href.startswith(("javascript:", "tel:", "mailto:")):
            continue
        url = urllib.parse.urljoin(base_url, href or "")
        key = f"{url}|{text}"
        if key in seen:
            continue
        seen.add(key)
        count_match = HIRING_COUNT_PATTERN.search(text)
        jobs.append({
            "platform": "careers",
            "platform_job_id": _job_id(url or base_url, text),
            "job_title": re.sub(r"\s*招(?:聘)?\s*\d{1,4}\s*人\s*$", "", text).strip(),
            "job_url": url or base_url,
            "city": "",
            "publish_date": "",
            "raw_hiring_text": count_match.group(0) if count_match else "",
            "recruitment_count": int(count_match.group(1)) if count_match else None,
            "source_provider": "company_site",
            "extraction_method": "anchor",
            "verification_status": "unverified",
        })
    return jobs


def discover_careers_links(collector: _Collector, base_url: str) -> list[str]:
    ranked: list[tuple[int, int, str]] = []
    for href, text in collector.anchors:
        haystack = f"{href or ''} {text}".lower()
        if not any(keyword in haystack for keyword in CAREERS_KEYWORDS):
            continue
        lowered_text = text.lower()
        absolute = urllib.parse.urljoin(base_url, href or "")
        if detect_ats([absolute]):
            score = 4  # 第三方招聘系统通常就是真实职位来源，优先级最高
        elif any(marker in lowered_text for marker in CAREERS_TEXT_PRIORITY):
            score = 3
        elif any(marker in str(href or "").lower() for marker in CAREERS_HREF_PRIORITY):
            score = 2
        else:
            score = 1
        if absolute and absolute not in {item[2] for item in ranked}:
            ranked.append((score, len(ranked), absolute))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return [item[2] for item in ranked]


def detect_ats(links: list[str]) -> list[dict]:
    """识别第三方招聘系统链接。"""
    found: list[dict] = []
    for link in links:
        host = urllib.parse.urlparse(link).netloc.lower()
        for domain, provider in ATS_PROVIDERS.items():
            if host.endswith(domain) and link not in {item["url"] for item in found}:
                found.append({"provider": provider, "domain": domain, "url": link})
    return found


def is_ats_root(url: str) -> bool:
    """ATS 厂商首页（如 www.mokahr.com/）是营销站，不是职位列表，不能当招聘页抽取。"""
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc.lower()
    return bool(detect_ats([url])) and parsed.path in ("", "/")


def extract_careers_page(html: str, base_url: str) -> dict:
    collector = parse_html(html)
    jobs: list[dict] = []
    method = "ats_render_required" if is_ats_root(base_url) else "none"
    if method != "ats_render_required":
        jobs = json_ld_jobs(collector, base_url)
        method = "json-ld"
        if not jobs:
            jobs = anchor_jobs(collector, base_url)
            method = "anchor" if jobs else "none"
    careers_links = discover_careers_links(collector, base_url)
    ats_candidates = detect_ats(careers_links)
    warnings = []
    if not jobs:
        if method == "ats_render_required":
            warnings.append("目标为第三方招聘系统首页，职位需在具体职位页渲染后抽取，建议用 Ego Lite")
        else:
            warnings.append("未识别到职位（页面可能为 JS 渲染，建议改用 Ego Lite 打开）")
    if ats_candidates:
        providers = "、".join(sorted({item["provider"] for item in ats_candidates}))
        warnings.append(f"检测到第三方招聘系统：{providers}（多为 JS 渲染，建议用 Ego Lite 打开后抽取）")
    return {
        "jobs": jobs,
        "extraction_method": method,
        "warnings": warnings,
        "careers_links": careers_links,
        "ats_candidates": ats_candidates,
    }


def extract_from_url(url: str, company_id: str) -> dict:
    final_url, body = fetch(url)
    if final_url is None:
        return {"company_id": company_id, "jobs": [], "_extraction": {"url": url, "error": body, "warnings": [body]}}
    result = extract_careers_page(body, final_url)
    result["company_id"] = company_id
    result["_extraction"] = {
        "url": final_url,
        "html_chars": len(body),
        "extraction_method": result.pop("extraction_method"),
        "warnings": result.pop("warnings"),
    }
    return result


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="企业官网招聘页抽取（只读）")
    parser.add_argument("--company-id", required=True)
    parser.add_argument("--url", help="直接指定招聘页 URL")
    parser.add_argument("--site", help="公司域名；会先抓首页并自动发现招聘页链接")
    parser.add_argument("--output")
    args = parser.parse_args(argv)

    target = args.url
    discovery_note = ""
    ats_candidates: list[dict] = []
    if not target and args.site:
        home = args.site if args.site.startswith("http") else f"https://www.{args.site}"
        final_url, body = fetch(home)
        if final_url is None:
            print(json.dumps({"error": body}, ensure_ascii=False))
            return 1
        links = discover_careers_links(parse_html(body), final_url)
        ats_candidates = detect_ats(links)
        if not links:
            print(json.dumps({"error": "首页未发现招聘页链接", "home": final_url}, ensure_ascii=False))
            return 1
        target = links[0]
        if detect_ats([target]):
            ats_candidates = detect_ats([target])
        discovery_note = f"{final_url} -> {target}"
    if not target:
        print(json.dumps({"error": "需要 --url 或 --site"}, ensure_ascii=False))
        return 2

    payload = extract_from_url(target, args.company_id)
    if discovery_note:
        payload.setdefault("_extraction", {})["discovery"] = discovery_note
    if ats_candidates:
        payload.setdefault("_extraction", {})["ats_candidates"] = ats_candidates
        providers = "、".join(sorted({item["provider"] for item in ats_candidates}))
        warnings = payload["_extraction"].setdefault("warnings", [])
        warnings.append(f"检测到第三方招聘系统：{providers}（多为 JS 渲染，建议用 Ego Lite 打开后抽取）")
    extraction_meta = payload.get("_extraction") or {}
    if extraction_meta.get("warnings"):
        deduped: list[str] = []
        for warning in extraction_meta["warnings"]:
            if warning not in deduped:
                deduped.append(warning)
        extraction_meta["warnings"] = deduped
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
        print(json.dumps({
            "output": args.output,
            "jobs": len(payload.get("jobs") or []),
            "method": payload.get("_extraction", {}).get("extraction_method"),
            "warnings": payload.get("_extraction", {}).get("warnings"),
        }, ensure_ascii=False, indent=2))
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

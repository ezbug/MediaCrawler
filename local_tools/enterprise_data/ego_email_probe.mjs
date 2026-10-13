/**
 * Ego Lite 企业邮箱补采探针（只读）。
 *
 * 在 Ego Lite TaskSpace 中打开企业官网及其联系/关于类页面，从渲染后的 DOM
 * 提取公开邮箱（mailto + 文本模式），输出 JSON。
 *
 * 用法（由同目录 ego_email_probe 包装器调用）：
 *   ego_email_probe --site haier.com=https://www.haier.com/ [--site ...] [--max-subs 3]
 */

const DEFAULT_TIMEOUT = 45000;

const GUESS_PATHS = [
  "/investor", "/investors", "/ir", "/tzzgx", "/investor-relations",
  "/contact", "/contact-us", "/contactus", "/lianxi", "/lxwm",
  "/about", "/about-us", "/guanyu",
  "/join", "/jobs", "/careers", "/zhaopin", "/hr", "/talent",
  "/news", "/media", "/press",
  "/service", "/kefu", "/support", "/hezuo", "/bd",
];

const PATH_RANKS = [
  [/investor|\/ir\/|ir\.|tzzgx|stockholder|shareholder/i, 0],
  [/contact|lianxi|lxwm|kefu|service|support|feedback|jubao|complain|wangzhan/i, 1],
  [/about|guanyu|intro/i, 2],
  [/join|job|career|zhaopin|hr\b|talent|recruit/i, 3],
  [/news|media|press|event|activity/i, 4],
];

function pathRank(url, text) {
  const hay = `${text || ""} ${url}`;
  for (const [pattern, rank] of PATH_RANKS) {
    if (pattern.test(hay)) return rank;
  }
  return 5;
}

export function parseArgs(argv) {
  const args = { space: "企业邮箱补采", maxSubs: 3, sites: [], extras: {} };
  for (let index = 0; index < argv.length; index += 1) {
    const flag = argv[index];
    const value = argv[index + 1];
    switch (flag) {
      case "--space":
        args.space = String(value || "");
        index += 1;
        break;
      case "--site": {
        const [domain, url] = String(value || "").split("=");
        if (!domain || !url) throw new Error(`--site 需要 domain=url 格式：${value}`);
        args.sites.push({ domain, home: url });
        index += 1;
        break;
      }
      case "--extra": {
        const [domain, url] = String(value || "").split("=");
        if (!domain || !url) throw new Error(`--extra 需要 domain=url 格式：${value}`);
        (args.extras[domain] = args.extras[domain] || []).push(url);
        index += 1;
        break;
      }
      case "--max-subs":
        args.maxSubs = Number(value);
        index += 1;
        break;
      default:
        throw new Error(`未知参数：${flag}`);
    }
  }
  if (!args.sites.length) throw new Error("至少需要一个 --site domain=url");
  if (!Number.isFinite(args.maxSubs) || args.maxSubs < 0) args.maxSubs = 0;
  return args;
}

/** 以下函数在页面上下文中执行，不能引用 Node 变量。 */
function extractEmailsInPage() {
  const cleaned = document.documentElement.innerHTML.replace(/data:[^"'\s)]+/g, " ");
  const found = new Set();
  for (const match of cleaned.matchAll(/mailto:([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})/gi)) {
    found.add(match[1].toLowerCase());
  }
  for (const raw of cleaned.matchAll(/[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}/g)) {
    const value = raw[0].toLowerCase();
    if (/\.(png|jpe?g|gif|svg|webp|ico|css|js|woff2?|ttf|eot|mp4|pdf)$/.test(value)) continue;
    if (/@\d+x\./.test(value)) continue;
    if (/crash\.|sentry\./i.test(value)) continue;
    if (/^[\da-f]{16,}@/.test(value)) continue;
    found.add(value);
  }
  return { emails: [...found], title: document.title, url: location.href };
}

function extractContactLinks(baseDomain) {
  const out = [];
  const seen = new Set();
  const wanted = /(contact|about|lianxi|lxwm|kefu|service|support|jubao|complain|investor|privacy|legal|联系|关于|客服|服务|举报|投诉|媒体|商务|招聘|人才|投资者|隐私|法律)/i;
  for (const anchor of document.querySelectorAll("a[href]")) {
    let href = "";
    try {
      href = new URL(anchor.getAttribute("href") || "", location.href).href.split("#")[0];
    } catch {
      continue;
    }
    if (!/^https?:/i.test(href)) continue;
    try {
      const host = new URL(href).hostname;
      if (host !== baseDomain && !host.endsWith(`.${baseDomain}`)) continue;
    } catch {
      continue;
    }
    if (seen.has(href)) continue;
    const text = (anchor.innerText || anchor.textContent || "").replace(/\s+/g, " ").trim().slice(0, 40);
    if (!wanted.test(`${text} ${href}`)) continue;
    seen.add(href);
    out.push({ url: href, text });
  }
  return out.slice(0, 30);
}

export async function main(argv) {
  const args = parseArgs(argv);
  const task = await taskSpace(args.space);
  const page = task.page("p1");
  console.error(`[probe] TaskSpace ${task.spaceId}（${args.space}）就绪`);
  const results = [];
  for (const site of args.sites) {
    const extra = args.extras[site.domain] || [];
    const siteResult = { domain: site.domain, home: site.home, pages: [], emails: [], warnings: [] };
    const emails = new Set();
    const visited = new Set();
    const visit = async (url, kind) => {
      try {
        try {
          await page.goto(url, { waitUntil: "domcontentloaded", timeout: DEFAULT_TIMEOUT });
        } catch (firstError) {
          await page.waitForTimeout(800);
          await page.goto(url, { waitUntil: "domcontentloaded", timeout: DEFAULT_TIMEOUT });
        }
        await page.waitForTimeout(700);
        for (let index = 0; index < 1; index += 1) {
          await page.mouse.wheel(0, 4000);
          await page.waitForTimeout(400);
        }
        const data = await page.evaluate(extractEmailsInPage);
        data.emails.forEach((item) => emails.add(item));
        let path = "";
        try {
          path = new URL(data.url).pathname;
        } catch {
          path = "";
        }
        siteResult.pages.push({ url: data.url, path, kind, title: data.title, emails: data.emails });
        return data;
      } catch (error) {
        const message = String((error && error.message) || error).slice(0, 200);
        siteResult.pages.push({ url, kind, emails: [], error: message });
        siteResult.warnings.push(`${url} 失败：${message}`);
        return null;
      }
    };
    visited.add(site.home.split("#")[0]);
    const homeData = await visit(site.home, "home");
    let candidates = extra.map((url) => ({ url, text: "" }));
    if (homeData) {
      const discovered = await page.evaluate(extractContactLinks, { baseDomain: site.domain });
      candidates = candidates.concat(discovered || []);
    }
    for (const path of GUESS_PATHS) {
      try {
        candidates.push({ url: new URL(path, site.home).href, text: "" });
      } catch {
        // 忽略非法 URL
      }
    }
    const sorted = candidates
      .filter((item) => item.url && !visited.has(item.url.split("#")[0]))
      .sort((a, b) =>
        pathRank(a.url, a.text) - pathRank(b.url, b.text) ||
        (a.text ? 0 : 1) - (b.text ? 0 : 1) ||
        a.url.length - b.url.length);
    let subs = 0;
    for (const item of sorted) {
      if (subs >= args.maxSubs) break;
      const clean = item.url.split("#")[0];
      if (visited.has(clean)) continue;
      visited.add(clean);
      subs += 1;
      await visit(clean, item.text || "sub");
    }
    siteResult.emails = [...emails];
    console.error(`[probe] ${site.domain}: ${siteResult.emails.length} emails / ${siteResult.pages.length} pages`);
    results.push(siteResult);
  }
  console.log(JSON.stringify({ sites: results }, null, 2));
}

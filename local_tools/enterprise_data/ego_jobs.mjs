/**
 * Ego Lite 招聘职位采集器（只读）。
 *
 * 在用户已登录的 TaskSpace 中打开招聘平台页面，滚动加载后从 DOM 提取职位卡片：
 * 标题、城市、薪资、链接、招聘人数（如有）。输出 JSON 供 import-jobs 使用。
 *
 * 用法（由 Python 包装器调用）：
 *   ego_jobs --taskspace 3 --page p1 --url <URL> --platform boss|zhaopin|liepin|moka|generic \
 *            --scrolls 3 --max-jobs 60
 */

const DEFAULT_TIMEOUT = 45000;

export function parseArgs(argv) {
  const args = { taskspace: 0, url: "", platform: "generic", page: "p1", scrolls: 3, maxJobs: 60 };
  for (let index = 0; index < argv.length; index += 1) {
    const flag = argv[index];
    const value = argv[index + 1];
    switch (flag) {
      case "--taskspace": args.taskspace = Number(value); index += 1; break;
      case "--url": args.url = String(value || ""); index += 1; break;
      case "--platform": args.platform = String(value || "generic"); index += 1; break;
      case "--page": args.page = String(value || "p1"); index += 1; break;
      case "--scrolls": args.scrolls = Number(value); index += 1; break;
      case "--max-jobs": args.maxJobs = Number(value); index += 1; break;
      default: throw new Error(`未知参数：${flag}`);
    }
  }
  if (!args.url) throw new Error("必须提供 --url");
  if (!args.taskspace) throw new Error("必须提供 --taskspace");
  if (!Number.isFinite(args.scrolls) || args.scrolls < 0) args.scrolls = 0;
  if (!Number.isFinite(args.maxJobs) || args.maxJobs <= 0) args.maxJobs = 60;
  return args;
}

/** 该函数在页面上下文中执行，不能引用 Node 变量。 */
function extractJobsInPage(payload) {
  const { platform, maxJobs } = payload;
  const JOB_HREF = /(\/job\/|\/jobs\/|job_detail|jobDetail|\/apply\/|\/social-recruitment\/|\/campus-recruitment\/)/i;
  const CITIES = [
    "北京", "上海", "广州", "深圳", "杭州", "成都", "武汉", "南京", "西安", "苏州", "长沙",
    "重庆", "天津", "郑州", "青岛", "合肥", "厦门", "福州", "济南", "大连", "宁波", "无锡",
    "东莞", "佛山", "珠海", "全国", "远程",
  ];
  const SALARY = /\d+(?:\.\d+)?\s*[-~—]\s*\d+(?:\.\d+)?\s*[kK千万]|\d+(?:\.\d+)?\s*[kK]|面议/;
  const HEADCOUNT = /招(?:聘)?\s*(\d{1,4})\s*人/;

  const hash = (text) => {
    let acc = 5381;
    for (let index = 0; index < text.length; index += 1) acc = ((acc * 33) ^ text.charCodeAt(index)) >>> 0;
    return acc.toString(16).padStart(8, "0");
  };

  const anchors = [...document.querySelectorAll("a[href]")].filter((anchor) => JOB_HREF.test(anchor.getAttribute("href") || ""));
  const jobs = [];
  const seen = new Set();
  for (const anchor of anchors) {
    if (jobs.length >= maxJobs) break;
    let href = "";
    try { href = new URL(anchor.getAttribute("href") || "", location.href).href; } catch { continue; }
    const title = (anchor.innerText || anchor.textContent || "").replace(/\s+/g, " ").trim();
    if (!title || title.length > 60) continue;
    const key = `${href}|${title}`;
    if (seen.has(key)) continue;
    seen.add(key);

    const hasSignal = (text) => SALARY.test(text) || HEADCOUNT.test(text) || CITIES.some((item) => text.includes(item));
    let block = anchor;
    let chosen = "";
    let fallback = "";
    let chosenElement = anchor;
    for (let level = 0; level < 5 && block.parentElement; level += 1) {
      block = block.parentElement;
      const candidate = (block.innerText || "").replace(/\s+/g, " ").trim();
      if (!candidate.includes(title) || candidate.length > 800) continue;
      if (!fallback) fallback = candidate;
      if (hasSignal(candidate)) { chosen = candidate; chosenElement = block; break; }
    }
    const text = (chosen || fallback || title).slice(0, 400);
    let employer = "";
    const employerNode = chosenElement.querySelector(
      [
        ".company-name",
        "[class*=company-name]",
        "[class*=companyName]",
        ".company-text .name",
        "[class*=employer]",
        ".boss-info .boss-name",  // BOSS 卡片：.boss-name 展示的是公司名
        ".boss-name",
      ].join(", "),
    );
    if (employerNode) employer = (employerNode.innerText || "").replace(/\s+/g, " ").trim().slice(0, 40);
    if (!employer) {
      employer = (text.split(/\s+/).find((line) => /(有限公司|集团|科技|股份|银行|研究院|中心|事务所|大学)$/.test(line)) || "").slice(0, 40);
    }
    const salary = (text.match(SALARY) || [""])[0];
    const city = CITIES.find((item) => text.includes(item)) || "";
    const countMatch = text.match(HEADCOUNT);
    jobs.push({
      platform,
      platform_job_id: hash(`${href}|${title}`),
      job_title: title,
      job_url: href,
      city,
      employer_name: employer,
      raw_hiring_text: [salary, countMatch ? countMatch[0] : ""].filter(Boolean).join(" / ").slice(0, 60),
      recruitment_count: countMatch ? Number(countMatch[1]) : null,
      source_provider: platform,
      extraction_method: "ego-dom",
      verification_status: "unverified",
    });
  }
  return { jobs, anchors: anchors.length, url: location.href, title: document.title };
}

export async function main(argv) {
  const args = parseArgs(argv);
  const task = await taskSpace(args.taskspace);
  const page = task.page(args.page);
  const warnings = [];
  await page.goto(args.url, { waitUntil: "domcontentloaded", timeout: DEFAULT_TIMEOUT });
  await page.waitForFunction(
    () => document.querySelectorAll('a[href*="job"], a[href*="jobs"], a[href*="apply"]').length >= 5,
    undefined,
    { timeout: 15000 },
  ).catch(() => warnings.push("等待职位链接超时，仍尝试提取"));
  for (let index = 0; index < args.scrolls; index += 1) {
    await page.mouse.wheel(0, 1800);
    await page.waitForTimeout(1200);
  }
  const data = await page.evaluate(extractJobsInPage, { platform: args.platform, maxJobs: args.maxJobs });
  if (!data.jobs.length) {
    warnings.push("未提取到职位：可能需要登录、切换城市或页面结构变化");
  }
  console.log(JSON.stringify({
    jobs: data.jobs,
    _extraction: {
      url: data.url,
      page_title: data.title,
      platform: args.platform,
      anchors: data.anchors,
      scrolls: args.scrolls,
      warnings,
    },
  }));
}

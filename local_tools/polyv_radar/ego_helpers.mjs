export async function waitForResults(page, selector, timeoutMs = 20000, stableRounds = 2) {
  const deadline = Date.now() + timeoutMs;
  let previous = -1;
  let stable = 0;
  while (Date.now() < deadline) {
    const count = await page.evaluate((value) => document.querySelectorAll(value).length, selector);
    if (count > 0) {
      stable = count === previous ? stable + 1 : 0;
      if (stable >= stableRounds) return count;
      previous = count;
    }
    await new Promise(resolve => setTimeout(resolve, 250));
  }
  return await page.evaluate((value) => document.querySelectorAll(value).length, selector);
}

export async function loadUntilStable(page, selector, maxItems, stableRounds = 3) {
  let previous = 0;
  let stable = 0;
  for (let round = 0; round < 24 && stable < stableRounds; round += 1) {
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
    await new Promise(resolve => setTimeout(resolve, 400));
    const count = await page.evaluate((value) => document.querySelectorAll(value).length, selector);
    if (count >= maxItems) break;
    stable = count === previous ? stable + 1 : 0;
    previous = count;
  }
}

export function requiresSearchLogin(bodyText, resultCount = 0) {
  if (Number(resultCount) > 0) return false;
  return /登录后即可搜索更多精彩视频|扫码登录/.test(String(bodyText || ""));
}

const SEARCH_EVENT_TERMS = [
  "企业直播", "直播", "公司年会", "年会", "经销商", "渠道大会", "员工培训", "企业培训", "企业内训",
  "新品", "新品发布会", "产品发布会", "发布会", "招商会", "医学会议", "学术会议", "金融投教", "投教直播", "企业大学",
  "课程版权", "防录屏", "防盗录", "视频加密", "海外发布会", "海外直播", "多语言直播", "webinar", "直播sdk",
  "app接直播", "直播api",
];
const SEARCH_SCENE_TERMS = [
  "公司", "企业", "机构", "员工", "经销商", "渠道", "培训", "投教", "年会", "招商会",
  "医学", "学术", "医生", "金融", "证券", "投资者", "海外", "多语言", "集成", "开发", "搭建",
];
const SEARCH_INTENT_TERMS = [
  "平台", "采购", "供应商", "服务商", "选型", "报价", "价格", "多少钱", "方案", "部署", "交付", "私有化",
  "sdk", "api", "并发", "策划", "推荐", "怎么选", "支持",
];
const SEARCH_DELIVERY_TERMS = [
  "直播", "培训", "平台", "方案", "供应商", "服务商", "系统", "部署", "交付", "在线", "sdk", "api",
  "防录屏", "防盗录", "视频加密", "webinar",
];
const SEARCH_NOISE_TERMS = [
  "王者荣耀", "kpl", "游戏", "动漫", "手机", "数码", "美食", "旅游", "留学", "工资", "离职", "相亲",
];

function normalizedSearchText(value) {
  return String(value || "").toLowerCase().replace(/[\s\u3000]+/g, "");
}

function keywordParts(value) {
  return String(value || "")
    .split(/[\s\u3000,，。.!！?？、/|+]+/)
    .map((part) => normalizedSearchText(part))
    .filter((part) => part.length >= 2);
}

export function cardTitleFromText(value) {
  const lines = String(value || "")
    .split(/\n+/)
    .map((line) => line.trim())
    .filter(Boolean);
  const meaningful = lines.filter((line) => {
    if (/^\d{1,2}:\d{2}(?::\d{2})?$/.test(line)) return false;
    if (/^\d[\d.万亿]*$/.test(line)) return false;
    if (/^@/.test(line)) return false;
    if (/^(刚刚|今天|昨天|前天|\d+(秒|分钟|小时|天|周|个月|年|月)(前)?|\d+(小时前|分钟前))$/.test(line)) return false;
    return true;
  });
  return meaningful.join(" ").trim();
}

export function isExpectedXhsNoteUrl(url, expectedId) {
  const match = String(url || "").match(/\/(?:explore|search_result)\/([a-zA-Z0-9]+)/);
  return Boolean(match && match[1] === String(expectedId || ""));
}

export function isGenericPlatformRedirect(sourceUrl, finalUrl) {
  try {
    const source = new URL(sourceUrl);
    const final = new URL(finalUrl || sourceUrl);
    const sourcePath = source.pathname.replace(/\/+$/, '') || '/';
    const finalPath = final.pathname.replace(/\/+$/, '') || '/';
    const sourceIsSpecific = /^\/(?:explore|video|question|article|p|answer|user\/profile|people)\/[^/]+/i.test(sourcePath);
    const finalIsGeneric = finalPath === '/' || /^\/(?:explore|search|home)$/i.test(finalPath);
    return source.origin === final.origin && sourceIsSpecific && finalIsGeneric;
  } catch (_) {
    return false;
  }
}

export function searchRelevance(keyword, text) {
  const normalized = normalizedSearchText(text);
  const parts = [...new Set(keywordParts(keyword))];
  const queryHits = parts.filter((part) => normalized.includes(part)).length;
  const eventMatches = SEARCH_EVENT_TERMS.filter((term) => normalized.includes(normalizedSearchText(term)));
  const sceneMatches = SEARCH_SCENE_TERMS.filter((term) => normalized.includes(normalizedSearchText(term)));
  const intentMatches = SEARCH_INTENT_TERMS.filter((term) => normalized.includes(normalizedSearchText(term)));
  const deliveryMatches = SEARCH_DELIVERY_TERMS.filter((term) => normalized.includes(normalizedSearchText(term)));
  const noiseMatches = SEARCH_NOISE_TERMS.filter((term) => normalized.includes(normalizedSearchText(term)));
  const eventHit = eventMatches.length > 0;
  const sceneHit = sceneMatches.length > 0;
  const intentHit = intentMatches.length > 0;
  const deliveryHit = deliveryMatches.length > 0;
  const technicalEventHit = eventMatches.some((term) => [
    "直播sdk", "直播api", "app接直播", "视频加密", "防录屏", "多语言直播", "webinar",
  ].includes(term)) || (normalized.includes("直播") && /sdk|api/.test(normalized));
  const technicalQueryHit = /sdk|api/.test(normalizedSearchText(keyword)) && /sdk|api/.test(normalized);
  const technicalQuery = /sdk|api|接口|app|应用/.test(normalizedSearchText(keyword));
  const technicalTitle = /sdk|api|接口|接入|集成|app|应用/.test(normalized);
  const technicalContextValid = !technicalQuery || technicalTitle;
  const strongBusinessHit = eventHit && sceneHit && technicalContextValid && (deliveryHit || intentHit || queryHits >= 2);
  const technicalBusinessHit = technicalEventHit && technicalContextValid && (technicalQueryHit || queryHits >= 1);
  const contextualPhoneNoise = noiseMatches.length === 1 && noiseMatches[0] === "手机" && eventHit && intentHit;
  const accepted = (strongBusinessHit || technicalBusinessHit) && (noiseMatches.length === 0 || contextualPhoneNoise);
  const score = (eventHit ? 3 : 0) + (sceneHit ? 2 : 0) + (intentHit ? 2 : 0) + Math.min(queryHits, 3) - (noiseMatches.length ? 5 : 0);
  return {
    accepted,
    score,
    queryHits,
    eventMatches,
    sceneMatches,
    intentMatches,
    deliveryMatches,
    noiseMatches,
  };
}

export function filterSearchResults(keyword, items) {
  return items
    .map((item) => {
      const text = item.searchText || [item.title, item.rawSnippet, item.text].filter(Boolean).join(" ");
      return { ...item, relevance: searchRelevance(keyword, text) };
    })
    .filter((item) => item.relevance.accepted)
    .sort((left, right) => right.relevance.score - left.relevance.score);
}

export function profileIdFromUrl(url, platform) {
  const value = String(url || "");
  const patterns = {
    dy: [/\/user\/([^/?#]+)/i],
    xhs: [/\/user\/profile\/([^/?#]+)/i],
    bili: [/space\.bilibili\.com\/(\d+)/i],
    zhihu: [/\/people\/([^/?#]+)/i],
  };
  for (const pattern of patterns[platform] || []) {
    const match = value.match(pattern);
    if (match) return match[1];
  }
  return "";
}

export function parseDisplayedTime(value, now = new Date()) {
  const text = String(value || "").trim();
  if (!text) return null;
  const base = new Date(now);
  const absolute = text.match(/(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})(?:\s+(\d{1,2}):(\d{2}))?/);
  if (absolute) {
    const [, year, month, day, hour = "00", minute = "00"] = absolute;
    return new Date(Date.UTC(Number(year), Number(month) - 1, Number(day), Number(hour), Number(minute)));
  }
  if (/刚刚|刚才/.test(text)) return base;
  const timeMatch = text.match(/(\d{1,2}):(\d{2})/);
  const withTime = (date) => {
    if (!timeMatch) return date;
    date.setUTCHours(Number(timeMatch[1]), Number(timeMatch[2]), 0, 0);
    return date;
  };
  if (/今天/.test(text)) return withTime(base);
  if (/昨天/.test(text)) return withTime(new Date(base.getTime() - 24 * 60 * 60 * 1000));
  const relative = text.match(/(\d+)\s*(秒|分钟|小时|天|周|月|个月|年)前/);
  if (!relative) return null;
  const amount = Number(relative[1]);
  const unit = relative[2];
  const milliseconds = {
    秒: 1000,
    分钟: 60 * 1000,
    小时: 60 * 60 * 1000,
    天: 24 * 60 * 60 * 1000,
    周: 7 * 24 * 60 * 60 * 1000,
    月: 30 * 24 * 60 * 60 * 1000,
    个月: 30 * 24 * 60 * 60 * 1000,
    年: 365 * 24 * 60 * 60 * 1000,
  }[unit];
  return milliseconds ? new Date(base.getTime() - amount * milliseconds) : null;
}

export function extractPublishedTimeText(value) {
  const lines = String(value || '')
    .split(/\n+/)
    .map((line) => line.trim())
    .filter(Boolean);
  const absolute = /20\d{2}[-/.]\d{1,2}[-/.]\d{1,2}(?:\s+\d{1,2}:\d{2})?/;
  const explicit = lines.find((line) => /(?:发表于|发布于|更新于|编辑于)/.test(line) && absolute.test(line));
  if (explicit) return explicit;
  return lines.find((line) => absolute.test(line) || /刚刚|刚才|今天|昨天|\d+\s*(秒|分钟|小时|天|周|月|个月|年)前/.test(line)) || '';
}

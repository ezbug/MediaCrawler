export async function loadUntilStable(page, selector, maxItems, stableRounds = 3) {
  let previous = 0;
  let stable = 0;
  for (let round = 0; round < 15 && stable < stableRounds; round += 1) {
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
    await new Promise(resolve => setTimeout(resolve, 700));
    const count = await page.evaluate((value) => document.querySelectorAll(value).length, selector);
    if (count >= maxItems) break;
    stable = count === previous ? stable + 1 : 0;
    previous = count;
  }
}

const SEARCH_EVENT_TERMS = [
  "企业直播", "公司年会", "年会直播", "经销商大会", "渠道大会", "员工培训", "企业培训", "企业内训",
  "新品发布会", "产品发布会", "招商会", "医学会议", "学术会议", "金融投教", "投教直播", "企业大学",
  "课程版权", "防录屏", "防盗录", "视频加密", "海外发布会", "多语言直播", "webinar", "直播sdk",
  "app接直播", "直播api",
];
const SEARCH_SCENE_TERMS = [
  "公司", "企业", "机构", "员工", "经销商", "渠道", "培训", "大会", "会议", "发布会", "课程", "投教",
  "年会", "招商会", "医院", "大学", "学校",
];
const SEARCH_INTENT_TERMS = [
  "平台", "采购", "供应商", "服务商", "选型", "报价", "价格", "多少钱", "方案", "部署", "交付", "私有化",
  "sdk", "api", "并发", "策划", "推荐", "怎么选", "支持",
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

export function searchRelevance(keyword, text) {
  const normalized = normalizedSearchText(text);
  const parts = [...new Set(keywordParts(keyword))];
  const queryHits = parts.filter((part) => normalized.includes(part)).length;
  const eventMatches = SEARCH_EVENT_TERMS.filter((term) => normalized.includes(normalizedSearchText(term)));
  const sceneMatches = SEARCH_SCENE_TERMS.filter((term) => normalized.includes(normalizedSearchText(term)));
  const intentMatches = SEARCH_INTENT_TERMS.filter((term) => normalized.includes(normalizedSearchText(term)));
  const noiseMatches = SEARCH_NOISE_TERMS.filter((term) => normalized.includes(normalizedSearchText(term)));
  const eventHit = eventMatches.length > 0;
  const sceneHit = sceneMatches.length > 0;
  const intentHit = intentMatches.length > 0;
  const strongBusinessHit = eventHit && (sceneHit || (intentHit && queryHits > 0));
  const contextualPhoneNoise = noiseMatches.length === 1 && noiseMatches[0] === "手机" && eventHit && intentHit;
  const accepted = (strongBusinessHit || queryHits >= 2) && (noiseMatches.length === 0 || contextualPhoneNoise);
  const score = (eventHit ? 3 : 0) + (sceneHit ? 2 : 0) + (intentHit ? 2 : 0) + Math.min(queryHits, 3) - (noiseMatches.length ? 5 : 0);
  return {
    accepted,
    score,
    queryHits,
    eventMatches,
    sceneMatches,
    intentMatches,
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

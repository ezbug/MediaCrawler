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

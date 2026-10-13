import fs from 'node:fs/promises';

export function allowedHost(company, host) {
  const all = [...(company.official_domains || []), ...(company.source_domains || [])];
  return all.some(d => host === d || host.endsWith(`.${d}`));
}

export async function collect(configPath, spaceId, outputPath) {
  const config = JSON.parse(await fs.readFile(configPath, 'utf8'));
  const task = await taskSpace(spaceId);
  const page = task.page('p1');
  const captures = [], errors = [], visited = new Set();

  async function capture(company, url) {
    const key = String(url).trim();
    if (!key || visited.has(key)) return;
    visited.add(key);
    try {
      await page.goto(key, { timeout: 25000, waitUntil: 'domcontentloaded' });
      for (let i = 0; i < 3; i += 1) {
        const current = await page.url();
        if (!current.includes('baidu.com/link') && !current.includes('wappass.baidu.com')) break;
        await page.waitForTimeout(1500);
      }
      const finalURL = await page.url();
      if (finalURL.includes('baidu.com/link') || finalURL.includes('wappass.baidu.com')) throw new Error('redirect_unresolved');
      const host = new URL(finalURL).hostname.toLowerCase();
      if (!allowedHost(company, host)) { errors.push({ company: company.name, stage: 'skip_host', url: finalURL }); return; }
      await page.waitForFunction(() => (document.body?.innerText || '').length > 200, undefined, { timeout: 8000 }).catch(() => {});
      const data = await page.evaluate(() => ({ url: location.href, title: document.title, text: (document.body?.innerText || '').slice(0, 60000) }));
      if (/验证码|安全验证|访问过于频繁/.test(data.title)) throw new Error('verification_required');
      captures.push({ ...data, company_id: company.id, captured_at: new Date().toISOString() });
    } catch (error) { errors.push({ company: company.name, stage: 'source', url: key, error: String(error) }); }
  }

  for (const company of config.companies) {
    for (const url of company.pages || []) await capture(company, url);
    for (const query of company.queries || []) {
      let links = [];
      try {
        await page.goto(`https://www.baidu.com/s?wd=${encodeURIComponent(query)}`, { timeout: 30000 });
        await page.waitForSelector('#content_left h3 a', { timeout: 10000 });
        links = await page.evaluate(() => [...document.querySelectorAll('#content_left h3 a[href]')].slice(0, 6).map(a => a.href));
      } catch (error) { errors.push({ company: company.name, stage: 'search', query, error: String(error) }); }
      for (const link of links.slice(0, 4)) await capture(company, link);
      await page.waitForTimeout(800);
    }
    for (const url of company.source_urls || []) await capture(company, url);
  }
  await fs.writeFile(outputPath, JSON.stringify({ captures, errors }, null, 2));
  console.log(JSON.stringify({ output: outputPath, captures: captures.length, errors: errors.length }));
}

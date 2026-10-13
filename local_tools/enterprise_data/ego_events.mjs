import fs from 'node:fs/promises';

export async function collect(configPath, spaceId, outputPath) {
  const config = JSON.parse(await fs.readFile(configPath, 'utf8'));
  const task = await taskSpace(spaceId);
  const page = task.page('p1');
  const captures = [], errors = [];
  for (const company of config.companies) {
    const urls = [...(company.source_urls || [])];
    try {
      const query = `${company.name} ${config.as_of?.slice(0, 4) || new Date().getFullYear()} 说明会 发布会 展会 培训 活动 公告`;
      await page.goto(`https://www.baidu.com/s?wd=${encodeURIComponent(query)}`, { timeout: 30000 });
      await page.waitForSelector('#content_left .result', { timeout: 10000 });
      const links = await page.evaluate(() => [...document.querySelectorAll('#content_left .result h3 a[href]')].slice(0, 5).map(a => a.href));
      urls.push(...links);
    } catch (error) { errors.push({ company: company.name, stage: 'search', error: String(error) }); }
    for (const url of [...new Set(urls)].slice(0, 7)) {
      try {
        await page.goto(url, { timeout: 30000 });
        const finalURL = await page.url();
        const host = new URL(finalURL).hostname.toLowerCase();
        if (!company.source_domains.some(d => host === d || host.endsWith(`.${d}`))) continue;
        await page.waitForFunction(() => document.body?.innerText.length > 200, undefined, { timeout: 10000 });
        const data = await page.evaluate(() => ({ url: location.href, title: document.title, text: document.body.innerText }));
        if (/验证码|安全验证|访问过于频繁/.test(data.title)) throw new Error('verification_required');
        captures.push({ ...data, company_id: company.id, captured_at: new Date().toISOString() });
      } catch (error) { errors.push({ company: company.name, stage: 'source', url, error: String(error) }); }
    }
  }
  await fs.mkdir(new URL('.', `file://${outputPath}`).pathname, { recursive: true });
  await fs.writeFile(outputPath, JSON.stringify({ captures, errors }, null, 2));
  console.log(JSON.stringify({ output: outputPath, captures: captures.length, errors: errors.length }));
}

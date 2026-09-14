import fs from 'node:fs/promises';

const inputPath = process.env.POLYV_WEB_INPUT;
const outputPath = process.env.POLYV_WEB_OUTPUT;
const candidates = JSON.parse(await fs.readFile(inputPath, 'utf-8'));

let task;
try {
  task = await takeOverTaskSpace(8);
} catch (error) {
  task = await taskSpace(8).catch(() => taskSpace('polyv public web verifier'));
}
const page = task.page('p1');
const evidence = [];

for (const candidate of candidates) {
  if (!candidate.company) continue;
  const query = `${candidate.company} ${candidate.event_type || '企业直播'} ${candidate.quote || ''}`.slice(0, 180);
  try {
    await page.goto(`https://www.bing.com/search?q=${encodeURIComponent(query)}`);
    await page.waitForLoadState({ timeout: 15000 }).catch(() => {});
    await new Promise(resolve => setTimeout(resolve, 1800));
    const results = await page.evaluate(() => {
      return Array.from(document.querySelectorAll('li.b_algo, [data-sokoban-container], .result')).slice(0, 5).map(item => {
        const anchor = item.querySelector('h2 a, a[href]');
        return {
          source_url: anchor?.href || '',
          title: anchor?.innerText?.trim() || '',
          snippet: item.innerText?.trim().replace(/\s+/g, ' ').slice(0, 500) || '',
          source_type: /新闻|news/i.test(item.innerText || '') ? 'news' : 'public_web',
          published_at: '',
        };
      }).filter(item => item.source_url && /^https?:\/\//i.test(item.source_url));
    });
    for (const result of results) evidence.push({ ...candidate, ...result });
  } catch (error) {
    console.error(`[WebVerifier] failed for ${candidate.company}:`, error.message);
  }
}

await fs.writeFile(outputPath, JSON.stringify({ evidence }, null, 2), 'utf-8');
console.log(`[WebVerifier] saved ${evidence.length} public sources to ${outputPath}`);


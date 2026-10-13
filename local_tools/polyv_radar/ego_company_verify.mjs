import fs from 'node:fs/promises';
import path from 'node:path';

const args = Object.fromEntries(process.argv.slice(2).reduce((pairs, value, i, values) => {
  if (value.startsWith('--')) pairs.push([value.slice(2), values[i + 1]]);
  return pairs;
}, []));
if (!args.taskspace || !args.output || !args.input) throw new Error('--taskspace, --output and --input are required');
const output = path.resolve(args.output);
await fs.mkdir(output, { recursive: true });
const seeds = JSON.parse(await fs.readFile(args.input, 'utf8'));
const page = (await taskSpace(Number(args.taskspace))).page('p1');
const results = [];
for (const seed of seeds) {
  const { error: priorError, ...identity } = seed;
  try {
    try {
      await page.goto(seed.official_url);
    } catch (error) {
      if (!String(error).includes('PageNavigationTimeoutError')) throw error;
    }
    await page.waitForTimeout(1500);
    const data = await page.evaluate(() => {
      const raw = document.body?.innerText || '';
      const redact = text => text.replace(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/ig, '[邮箱已省略]')
        .replace(/(?:\+\d{1,3}[\s-]*)?(?:1[3-9]\d[\s-]*)\d{4}[\s-]*\d{4}/g, '[电话已省略]')
        .replace(/400[\s-]*\d{3,4}[\s-]*\d{3,4}/g, '[电话已省略]')
        .replace(/\b0\d{2,3}[- ]+\d{3,4}[ -]*\d{4}\b/g, '[电话已省略]')
        .replace(/(?:\+?86[- ]?)?1[3-9]\d{9}/g, '[电话已省略]')
        .replace(/(?:0\d{2,3}[- ]?)?\d{7,8}/g, '[号码已省略]');
      return {
        url: location.href, title: document.title,
        blocked: /验证码|安全验证|Access Denied|Just a moment/i.test(document.title),
        text: redact(raw).slice(0,18000),
        links: [...document.querySelectorAll('a[href]')]
          .filter(a => /联系我们|关于我们|公司简介|企业内训|公开课|课程|微信公众号|小红书|抖音|哔哩|知乎/.test(a.innerText || ''))
          .filter(a => /^https?:/.test(a.href))
          .map(a => ({ text: a.innerText.trim().slice(0,90), url: a.href })).slice(0,70),
      };
    });
    results.push({ ...identity, prior_error: priorError || null, checked_at: new Date().toISOString(), ...data });
    console.log({ seed: seed.title, title: data.title, length: data.text.length, blocked: data.blocked });
    if (data.blocked) break;
  } catch (error) {
    results.push({ ...identity, prior_error: priorError || null, checked_at: new Date().toISOString(), error: String(error) });
    console.log({ seed: seed.title, error: String(error).slice(0,200) });
  }
  await fs.writeFile(path.join(output, 'official-company-checks.json'), JSON.stringify(results, null, 2));
}
await fs.writeFile(path.join(output, 'official-company-checks.json'), JSON.stringify(results, null, 2));

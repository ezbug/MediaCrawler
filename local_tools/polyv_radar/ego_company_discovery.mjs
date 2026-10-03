import fs from 'node:fs/promises';
import path from 'node:path';

const args = Object.fromEntries(process.argv.slice(2).reduce((pairs, value, index, values) => {
  if (value.startsWith('--')) pairs.push([value.slice(2), values[index + 1]]);
  return pairs;
}, []));
if (!args.taskspace || !args.output) throw new Error('--taskspace and --output are required');
const queries = args.queries ? JSON.parse(await fs.readFile(args.queries, 'utf8')) : [
  '企业管理培训机构 官网 内训 公开课',
  '领导力培训机构 企业内训 官网 联系我们',
  '企业培训公司 公开课 管理培训 官网',
  '企业培训 咨询 培训机构 官网 广州 深圳',
];
const output = path.resolve(args.output);
await fs.mkdir(output, { recursive: true });
const page = (await taskSpace(Number(args.taskspace))).page('p1');
const results = [];
for (const query of queries) {
  await page.goto(`https://www.baidu.com/s?wd=${encodeURIComponent(query)}`);
  await page.waitForTimeout(1800);
  const data = await page.evaluate(() => ({
    blocked: /验证码|安全验证|百度安全验证/.test(document.title),
    results: [...document.querySelectorAll('#content_left h3 a')]
      .filter(a => !a.href.includes('/baidu.php'))
      .map(a => ({
        title: a.innerText, result_url: a.href,
        official_url: a.closest('[mu]')?.getAttribute('mu') || a.closest('[data-landurl]')?.getAttribute('data-landurl') || '',
        snippet: a.closest('.result,.c-container')?.innerText.slice(0,700) || '',
      })),
  }));
  results.push({ query, observed_at: new Date().toISOString(), ...data });
  await fs.writeFile(path.join(output, 'company-search-results.json'), JSON.stringify(results, null, 2));
  console.log({ query, count: data.results.length, blocked: data.blocked });
  if (data.blocked) break;
}

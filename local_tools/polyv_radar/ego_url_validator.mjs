import fs from 'node:fs/promises';

const inputPath = process.env.POLYV_URL_INPUT;
const outputPath = process.env.POLYV_URL_OUTPUT;
const input = JSON.parse(await fs.readFile(inputPath, 'utf-8'));

const taskspaceId = Number(process.env.POLYV_TASKSPACE_ID);
if (!Number.isInteger(taskspaceId) || taskspaceId <= 0) throw new Error('需要有效的 POLYV_TASKSPACE_ID');
const task = await takeOverTaskSpace(taskspaceId);
const page = task.page('p1');
const results = [];
const checkedAt = () => new Date().toISOString();

for (const url of input.urls || []) {
  const result = {
    url,
    status: 'error',
    http_status: 0,
    final_url: '',
    reason: '',
    checked_at: checkedAt(),
  };
  try {
    const response = await page.goto(url);
    await page.waitForLoadState({ timeout: 15000 }).catch(() => {});
    result.http_status = Number(response?.status?.() || response?.status || 0);
    result.final_url = await page.url();
    const pageData = await page.evaluate(() => ({
      title: document.title || '',
      text: (document.body?.innerText || '').slice(0, 12000),
      hasMain: Boolean(document.body?.innerText?.trim()),
    }));
    result.title = pageData.title;
    const pageText = `${pageData.title}\n${pageData.text}\n${result.final_url}`;
    if (/\/404(?:[/?#]|$)|404页面|页面不存在|内容不存在|视频不存在|笔记不存在|问题不存在|Not Found/i.test(pageText)) {
      result.status = 'not_found';
      result.reason = '页面显示不存在或 404';
    } else if (/登录后查看|请先登录|登录\/去登录|captcha|验证后继续|访问受限|安全验证|too many requests|forbidden/i.test(pageText)) {
      result.status = 'blocked';
      result.reason = '需要登录或被平台拦截';
    } else if (!pageData.hasMain) {
      result.status = 'failed';
      result.reason = '页面没有可读正文';
    } else if (result.http_status >= 400) {
      result.status = result.http_status === 429 ? 'blocked' : 'failed';
      result.reason = `HTTP ${result.http_status}`;
    } else {
      result.status = 'ok';
      result.reason = 'Ego Lite页面可访问且有可读内容';
    }
  } catch (error) {
    result.reason = String(error?.message || error).slice(0, 240);
    try { result.final_url = await page.url(); } catch (_) {}
  }
  results.push(result);
}

await fs.writeFile(outputPath, JSON.stringify({ results }, null, 2), 'utf-8');
console.log(`[UrlValidator] checked ${results.length} URLs`);

import fs from 'node:fs/promises';
import path from 'node:path';

const inputPath = process.env.POLYV_LOCATOR_INPUT;
const outputPath = process.env.POLYV_LOCATOR_OUTPUT;
const input = JSON.parse(await fs.readFile(inputPath, 'utf-8'));
const taskspaceId = Number(process.env.POLYV_TASKSPACE_ID);
const screenshotDir = process.env.POLYV_LOCATOR_SCREENSHOT_DIR || '';

if (!Number.isInteger(taskspaceId) || taskspaceId <= 0) throw new Error('需要有效的 POLYV_TASKSPACE_ID');
const task = await taskSpace(taskspaceId);
const page = task.page('p1');

const normalize = (value) => String(value || '').toLowerCase().replace(/[\s\u3000]+/g, ' ').trim();
const timePattern = /刚刚|刚才|今天|昨天|\d+\s*(秒|分钟|小时|天|周|月|个月|年)前|20\d{2}[-/.]\d{1,2}[-/.]\d{1,2}/;
const notFoundPattern = /\/404(?:[/?#]|$)|404页面|页面不存在|内容不存在|视频不存在|笔记不存在|问题不存在|当前笔记暂时无法浏览|Not Found/i;
const blockedPattern = /登录后查看|请先登录|登录\/去登录|captcha|验证后继续|访问受限|安全验证|too many requests|forbidden/i;

function attributes(node) {
  return Object.fromEntries(Array.from(node?.attributes || []).map((attribute) => [attribute.name, attribute.value]));
}

function extractLines(node) {
  return (node?.innerText || '').split('\n').map((line) => line.trim()).filter(Boolean);
}

function extractStandardComment(node, platform) {
  const lines = extractLines(node);
  if (lines.length < 2) return null;
  const authorLink = node.querySelector('a[href*="/user/"], a[href*="/user/profile/"], a[href*="/people/"]');
  const author = authorLink?.innerText?.trim() || lines[0];
  const textLines = lines.slice(1).filter((line) => line !== '...' && line !== '作者' && line !== '分享' && line !== '回复' && !/^\d+$/.test(line) && !timePattern.test(line));
  const text = textLines.join(' ').trim();
  if (!text) return null;
  const attrs = attributes(node);
  const nativeCommentId = attrs['data-comment-id'] || attrs['data-cid'] || attrs['data-rpid'] || attrs['data-id'] || '';
  const nativeParentId = attrs['data-root-id'] || attrs['data-parent-id'] || attrs['data-root'] || '';
  const commentLink = node.querySelector('a[href*="comment"], a[href*="reply"], a[href*="#reply"]');
  const publishedAtRaw = [...lines].reverse().find((line) => timePattern.test(line)) || '';
  return {
    native_comment_id: nativeCommentId,
    native_parent_id: nativeParentId,
    parent_comment_id: nativeParentId,
    comment_url: commentLink?.href || '',
    source_type: nativeParentId ? 'reply' : 'comment',
    author,
    author_url: authorLink?.href || '',
    text,
    published_at_raw: publishedAtRaw,
  };
}

async function extractBiliComments() {
  return page.evaluate(() => {
    const timePattern = /刚刚|刚才|今天|昨天|\d+\s*(秒|分钟|小时|天|周|月|个月|年)前|20\d{2}[-/.]\d{1,2}[-/.]\d{1,2}/;
    const attributes = (node) => Object.fromEntries(Array.from(node?.attributes || []).map((attribute) => [attribute.name, attribute.value]));
    const host = document.querySelector('bili-comments');
    const threads = Array.from(host?.shadowRoot?.querySelectorAll('bili-comment-thread-renderer') || []);
    return threads.map((thread) => {
      const comment = thread.shadowRoot?.querySelector('#comment');
      if (!comment?.shadowRoot) return null;
      const userInfo = comment.shadowRoot.querySelector('bili-comment-user-info');
      const richText = comment.shadowRoot.querySelector('bili-rich-text');
      const authorLink = userInfo?.shadowRoot?.querySelector('a[href*="space.bilibili.com"]');
      const text = richText?.shadowRoot?.querySelector('#contents')?.innerText || richText?.innerText || '';
      if (!text.trim()) return null;
      const threadAttrs = attributes(thread);
      const commentAttrs = attributes(comment);
      const nativeCommentId = threadAttrs['data-rpid'] || threadAttrs['data-comment-id'] || commentAttrs['data-rpid'] || commentAttrs['data-comment-id'] || '';
      const nativeParentId = threadAttrs['data-root'] || threadAttrs['data-parent-id'] || commentAttrs['data-root'] || commentAttrs['data-parent-id'] || '';
      const commentLink = Array.from(comment.shadowRoot.querySelectorAll('a[href]')).find((anchor) => /reply|comment/i.test(anchor.getAttribute('href') || ''));
      const publishedAtRaw = [...(comment.shadowRoot.innerText || '').split('\n').map((line) => line.trim()).filter(Boolean)].reverse().find((line) => timePattern.test(line)) || '';
      return {
        native_comment_id: nativeCommentId,
        native_parent_id: nativeParentId,
        parent_comment_id: nativeParentId,
        comment_url: commentLink?.href || '',
        source_type: nativeParentId ? 'reply' : 'comment',
        author: authorLink?.innerText?.trim() || 'B站用户',
        author_url: authorLink?.href || '',
        text: text.trim(),
        published_at_raw: publishedAtRaw,
      };
    }).filter(Boolean);
  });
}

async function readPage(platform) {
  return page.evaluate((currentPlatform) => {
    const body = document.body?.innerText || '';
    const title = document.title || '';
    const comments = currentPlatform === 'bili'
      ? []
      : Array.from(document.querySelectorAll(
          currentPlatform === 'dy'
            ? '[data-e2e="comment-item"]'
            : currentPlatform === 'xhs'
              ? '.parent-comment, .comment-item'
              : '.CommentItemV2, .CommentItem, [class*="CommentItem"]'
        )).map((node) => {
          const lines = (node.innerText || '').split('\n').map((line) => line.trim()).filter(Boolean);
          if (lines.length < 2) return null;
          const authorLink = node.querySelector('a[href*="/user/"], a[href*="/user/profile/"], a[href*="/people/"]');
          const author = authorLink?.innerText?.trim() || lines[0];
          const textLines = lines.slice(1).filter((line) => line !== '...' && line !== '作者' && line !== '分享' && line !== '回复' && !/^\d+$/.test(line) && !/刚刚|刚才|今天|昨天|\d+\s*(秒|分钟|小时|天|周|月|个月|年)前|20\d{2}[-/.]\d{1,2}[-/.]\d{1,2}/.test(line));
          const text = textLines.join(' ').trim();
          if (!text) return null;
          const attrs = Object.fromEntries(Array.from(node.attributes || []).map((attribute) => [attribute.name, attribute.value]));
          const nativeCommentId = attrs['data-comment-id'] || attrs['data-cid'] || attrs['data-rpid'] || attrs['data-id'] || '';
          const nativeParentId = attrs['data-root-id'] || attrs['data-parent-id'] || attrs['data-root'] || '';
          const commentLink = node.querySelector('a[href*="comment"], a[href*="reply"], a[href*="#reply"]');
          const publishedAtRaw = [...lines].reverse().find((line) => /刚刚|刚才|今天|昨天|\d+\s*(秒|分钟|小时|天|周|月|个月|年)前|20\d{2}[-/.]\d{1,2}[-/.]\d{1,2}/.test(line)) || '';
          return { native_comment_id: nativeCommentId, native_parent_id: nativeParentId, parent_comment_id: nativeParentId, comment_url: commentLink?.href || '', source_type: nativeParentId ? 'reply' : 'comment', author, author_url: authorLink?.href || '', text, published_at_raw: publishedAtRaw };
        }).filter(Boolean);
    return { title, body: body.slice(0, 30000), hasBody: Boolean(body.trim()), comments };
  }, platform);
}

async function clickExpanders(platform) {
  if (platform === 'bili') return;
  await page.evaluate((currentPlatform) => {
    const patterns = currentPlatform === 'dy' ? /展开.*回复|查看更多回复/ : /展开.*回复|查看全部回复|更多回复/;
    for (const button of Array.from(document.querySelectorAll('button, [role="button"], span, div'))) {
      const text = (button.innerText || '').trim();
      if (text && patterns.test(text) && text.length < 30) button.click();
    }
  }, platform).catch(() => {});
}

async function collectComments(platform, maxRounds = 10) {
  let previous = -1;
  let stable = 0;
  for (let round = 0; round < maxRounds && stable < 3; round += 1) {
    await clickExpanders(platform);
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight)).catch(() => {});
    await page.waitForTimeout(450);
    const count = platform === 'bili'
      ? await page.evaluate(() => document.querySelector('bili-comments')?.shadowRoot?.querySelectorAll('bili-comment-thread-renderer')?.length || 0)
      : (await readPage(platform)).comments.length;
    stable = count === previous ? stable + 1 : 0;
    previous = count;
  }
  if (platform === 'bili') return await extractBiliComments();
  return (await readPage(platform)).comments;
}

function classifyPage(state, finalUrl) {
  const searchable = `${state.title}\n${state.body}\n${finalUrl}`;
  if (notFoundPattern.test(searchable)) return ['not_found', '页面显示不存在或404'];
  if (blockedPattern.test(searchable)) return ['blocked', '需要登录或被平台拦截'];
  if (!state.hasBody) return ['error', '页面没有可读内容'];
  return ['ok', '页面可访问'];
}

function matchComment(comments, candidate) {
  const expectedAuthor = normalize(candidate.user);
  const expectedQuote = normalize(candidate.quote);
  let matches = comments.map((comment, index) => ({ comment, index, method: 'author_quote' })).filter(({ comment }) => (
    candidate.native_comment_id && comment.native_comment_id && candidate.native_comment_id === comment.native_comment_id
  ) || (
    normalize(comment.author) === expectedAuthor && normalize(comment.text) === expectedQuote
  ));
  if (candidate.parent_comment_id) {
    const byParent = matches.filter(({ comment }) => [comment.parent_comment_id, comment.native_parent_id].map(String).includes(String(candidate.parent_comment_id)));
    if (byParent.length) matches = byParent;
  }
  if (matches.length === 1) {
    const match = matches[0];
    return { status: 'verified', index: match.index, method: match.comment.native_comment_id ? 'native_id' : match.method, comment: match.comment, reason: '作者和原话唯一匹配' };
  }
  if (matches.length > 1) return { status: 'ambiguous', reason: '作者和原话匹配多个评论' };
  return { status: 'not_found', reason: '页面中未找到对应作者和原话' };
}

const results = [];
for (const candidate of input.candidates || []) {
  const result = {
    ...candidate,
    status: 'error',
    locator_method: '',
    locator_url: '',
    final_url: '',
    matched_author: '',
    matched_quote: '',
    reason: '',
    verified_at: new Date().toISOString(),
    screenshot_path: '',
  };
  try {
    await page.goto(candidate.content_url);
    await page.waitForLoadState({ timeout: 15000 }).catch(() => {});
    await page.waitForTimeout(700);
    result.final_url = await page.url();
    const initialState = await readPage(candidate.platform);
    const [pageStatus, pageReason] = classifyPage(initialState, result.final_url);
    if (pageStatus !== 'ok') {
      result.status = pageStatus;
      result.reason = pageReason;
    } else if (['post', 'answer', 'content'].includes(candidate.source_type)) {
      const expected = normalize(candidate.quote).slice(0, 80);
      const visible = normalize(`${initialState.title}\n${initialState.body}`);
      if (expected && !visible.includes(expected)) {
        result.status = 'not_found';
        result.reason = '内容页面可访问，但未找到对应原文片段';
      } else {
        result.status = 'verified';
        result.locator_method = 'direct_content_url';
        result.locator_url = candidate.content_url;
        result.matched_author = candidate.user || '';
        result.matched_quote = candidate.quote || '';
        result.reason = '内容页面和原文片段可访问';
      }
    } else {
      const comments = await collectComments(candidate.platform, 10);
      const match = matchComment(comments, candidate);
      result.status = match.status;
      result.locator_method = match.method || '';
      result.matched_author = match.comment?.author || '';
      result.matched_quote = match.comment?.text || '';
      result.reason = match.reason;
      result.locator_url = match.comment?.comment_url || candidate.content_url;
      if (match.status === 'verified' && !result.locator_url) result.locator_url = candidate.content_url;
      if (match.status === 'verified' && screenshotDir) {
        await fs.mkdir(screenshotDir, { recursive: true });
        const safe = `${candidate.platform}-${candidate.content_id}-${candidate.comment_id || 'content'}`.replace(/[^a-zA-Z0-9_.-]+/g, '_');
        result.screenshot_path = path.join(screenshotDir, `${safe}.png`);
        await page.screenshot({ path: result.screenshot_path }).catch(() => { result.screenshot_path = ''; });
      }
    }
  } catch (error) {
    result.reason = String(error?.message || error).slice(0, 300);
    try { result.final_url = await page.url(); } catch (_) {}
  }
  results.push(result);
}

await fs.mkdir(path.dirname(outputPath), { recursive: true });
await fs.writeFile(outputPath, JSON.stringify({ results }, null, 2), 'utf-8');
console.log(`[CommentLocator] checked ${results.length} candidates in Ego Lite TaskSpace ${taskspaceId}`);

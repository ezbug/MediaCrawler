import fs from 'node:fs/promises';
import path from 'node:path';
import { extractPublishedTimeText, filterSearchResults, normalizeZhihuCommentLines, parseDisplayedTime, profileIdFromUrl, waitForResults } from './ego_helpers.mjs';

const args = process.argv.slice(2);
const keyword = process.env.KEYWORD || args[0] || "员工培训";
const maxContents = parseInt(process.env.MAX_CONTENTS || args[1] || "5", 10);
const maxComments = parseInt(process.env.MAX_COMMENTS || args[2] || "10", 10);
const outputDir = process.env.OUTPUT_DIR || args[3] || `/Users/sexpistole111/Documents/workplace/polyv-radar-data/raw/20260914-zhihu/zhihu/${keyword}`;

await fs.mkdir(outputDir, { recursive: true });

const taskspaceId = Number(process.env.POLYV_TASKSPACE_ID);
if (!Number.isInteger(taskspaceId) || taskspaceId <= 0) throw new Error('需要有效的 POLYV_TASKSPACE_ID');
const task = await taskSpace(taskspaceId);

const page = task.page("p1");

async function openZhihuComments(page) {
  const opened = await page.evaluate(() => {
    const buttons = Array.from(document.querySelectorAll('button'));
    const target = buttons.find((button) => {
      const text = (button.innerText || '').replace(/\s+/g, ' ');
      return /\d+\s*条评论/.test(text);
    }) || buttons.find((button) => /评论/.test(button.innerText || button.getAttribute('aria-label') || ''));
    if (!target) return false;
    target.click();
    return true;
  });
  if (opened) await page.waitForTimeout(300);
  return opened;
}

async function loadZhihuComments(page, maxComments) {
  let previous = 0;
  let stable = 0;
  for (let round = 0; round < 12 && stable < 2; round += 1) {
    const count = await page.evaluate(() => {
      const seen = new Set();
      for (const link of Array.from(document.querySelectorAll('a[href*="/people/"]'))) {
        let node = link.parentElement;
        for (let depth = 0; node && depth < 8; depth += 1, node = node.parentElement) {
          const text = (node.innerText || '').trim();
          const profileCount = (node.matches('a[href*="/people/"]') ? 1 : 0) + node.querySelectorAll('a[href*="/people/"]').length;
          if (profileCount === 1 && text.includes('回复') && text.length > 20 && text.length < 2200) {
            seen.add(text);
            break;
          }
        }
      }
      return seen.size;
    });
    if (count >= maxComments) break;
    stable = count === previous ? stable + 1 : 0;
    previous = count;
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
    await page.waitForTimeout(300);
  }
}

console.log(`[ZhihuCrawler] Searching Zhihu for "${keyword}" (max ${maxContents} items)...`);
const searchUrl = `https://www.zhihu.com/search?type=content&q=${encodeURIComponent(keyword)}`;
await page.goto(searchUrl);
await page.waitForLoadState({ timeout: 15000 }).catch(() => {});
// Zhihu renders empty result-card placeholders before the real search links arrive.
// Wait for a content URL so the following extraction cannot race the result hydration.
await waitForResults(page, 'a[href*="/question/"], a[href*="/answer/"], a[href*="/p/"]');

const candidateItems = await page.evaluate(() => {
  const items = document.querySelectorAll('.SearchResult-Card, [class*="SearchResult-Card"], .Card, .ContentItem');
  const seen = new Set();
  const list = [];
  for (const item of items) {
    const link = item.querySelector('a[href*="/question/"], a[href*="/p/"]');
    if (!link) continue;
    const href = link.href.split('?')[0];
    if (seen.has(href)) continue;
    seen.add(href);

    const title = link.innerText.trim();
    const textEl = item.querySelector('.RichText, [class*="content"]');
    const text = textEl ? textEl.innerText.trim() : "";
    const authorEl = item.querySelector('.AuthorInfo-name, [class*="AuthorInfo"] a, [class*="author"]');
    const author = authorEl ? authorEl.innerText.trim() : "";

    list.push({
      url: href,
      title,
      searchText: title,
      text,
      author
    });
  }
  return list;
});

const relevantItems = filterSearchResults(keyword, candidateItems);
const targetItems = relevantItems.slice(0, maxContents);
console.log(`[ZhihuCrawler] Found ${candidateItems.length} raw candidates, ${relevantItems.length} relevant, selected ${targetItems.length} items.`);
if (relevantItems.length === 0) {
  console.error(`[ZhihuCrawler] No relevant content candidates found for "${keyword}".`);
  process.exitCode = 2;
}

const contents = [];
const comments = [];

for (let i = 0; i < targetItems.length; i++) {
  const item = targetItems[i];
  console.log(`[ZhihuCrawler] (${i + 1}/${targetItems.length}) Fetching: ${item.url}`);
  try {
    await page.goto(item.url);
    await page.waitForLoadState({ timeout: 15000 }).catch(() => {});
    await openZhihuComments(page);
    await loadZhihuComments(page, maxComments);

    const pageData = await page.evaluate(() => {
      const titleEl = document.querySelector('h1, .QuestionHeader-title');
      const richTextEl = document.querySelector('.RichContent-inner, .RichText, .Post-RichText');
      const authorLinks = Array.from(document.querySelectorAll('a[href*="/people/"]'));
      const authorLink = authorLinks.find((link) => {
        const href = link.getAttribute('href') || '';
        const text = (link.innerText || '').trim();
        return text && !/\/people\/[^/?#]+\/(answers|posts|followers|following|questions|collections)(?:[/?#]|$)/.test(href);
      }) || authorLinks.find((link) => (link.innerText || '').trim());
      const authorEl = authorLink || document.querySelector('.AuthorInfo-name');
      const tags = Array.from(document.querySelectorAll('.QuestionHeader-topics .Tag, a[href*="/topic/"]')).map(a => a.innerText.trim());

      const rawComments = [];
      const seenComments = new Set();
      const readAttr = (node, name) => {
        let current = node;
        for (let depth = 0; current && depth < 8; depth += 1, current = current.parentElement) {
          const value = current.getAttribute?.(name);
          if (value) return value;
        }
        return '';
      };
      for (const profileLink of Array.from(document.querySelectorAll('a[href*="/people/"]'))) {
        const href = profileLink.getAttribute('href') || '';
        if (/\/people\/[^/?#]+\/(answers|posts|followers|following|questions|collections)(?:[/?#]|$)/.test(href)) continue;
        let block = profileLink.parentElement;
        for (let depth = 0; block && depth < 8; depth += 1, block = block.parentElement) {
          const lines = (block.innerText || '').split('\n').map(line => line.trim()).filter(Boolean);
          const profileCount = (block.matches('a[href*="/people/"]') ? 1 : 0) + block.querySelectorAll('a[href*="/people/"]').length;
          if (profileCount !== 1 || !lines.join(' ').includes('回复') || lines.join(' ').length <= 20 || lines.join(' ').length >= 2200) continue;
          const author = profileLink.innerText?.trim() || '知乎用户';
          const key = `${href}:${lines.join('|')}`;
          if (seenComments.has(key)) break;
          seenComments.add(key);
          const publishedAtRaw = [...lines].reverse().find(line => /刚刚|刚才|今天|昨天|\d+\s*(秒|分钟|小时|天|周|月|个月|年)前|\d{1,2}[-/.]\d{1,2}\s*[·\-]|20\d{2}[-/.]\d{1,2}[-/.]\d{1,2}/.test(line)) || '';
          const nativeCommentId = readAttr(block, 'data-comment-id') || readAttr(block, 'data-id');
          const nativeParentId = readAttr(block, 'data-parent-id') || readAttr(block, 'data-root-id');
          const commentLink = block.querySelector('a[href*="comment"], a[href*="#"]');
          rawComments.push({
            comment_id: `zh_cm_${rawComments.length}`,
            native_comment_id: nativeCommentId,
            native_parent_id: nativeParentId,
            comment_url: commentLink?.href || '',
            source_type: nativeParentId ? 'reply' : 'comment',
            published_at_raw: publishedAtRaw,
            author,
            author_url: profileLink.href || '',
            parent_comment_id: readAttr(block, 'data-parent-id'),
            lines,
            likes: 0,
          });
          break;
        }
      }

      return {
        title: titleEl ? titleEl.innerText.trim() : "",
        text: richTextEl ? richTextEl.innerText.trim() : "",
        author: authorEl ? authorEl.innerText.trim() : "",
        author_url: authorLink?.href || "",
        tags,
        rawComments,
        bodyText: document.body?.innerText || "",
      };
    });

    const matchId = item.url.match(/\/(?:question\/\d+\/answer|p|question)\/(\d+)/);
    const contentId = matchId ? matchId[1] : `zh_${i}_${Date.now()}`;

    const publishedAtRaw = extractPublishedTimeText(pageData.bodyText);
    const contentRecord = {
      platform: "zhihu",
      content_id: contentId,
      title: pageData.title || item.title || "知乎问答",
      text: (pageData.text || item.text || item.title).slice(0, 1500),
      url: item.url,
      author: pageData.author || item.author || "",
      author_url: pageData.author_url || "",
      author_id: profileIdFromUrl(pageData.author_url, "zhihu"),
      tags: pageData.tags,
      source_keyword: keyword,
      published_at_raw: publishedAtRaw,
      create_time: parseDisplayedTime(publishedAtRaw)?.toISOString() || ""
    };
    contents.push(contentRecord);

    const itemComments = (pageData.rawComments || [])
      .map((c) => ({ ...c, text: normalizeZhihuCommentLines(c.lines, c.author) }))
      .filter((c) => c.text)
      .slice(0, maxComments)
      .map(c => ({
      platform: "zhihu",
      comment_id: `${contentId}_${c.native_comment_id || c.comment_id}`,
      content_id: contentId,
      text: c.text,
      author: c.author,
      author_url: c.author_url || "",
      author_id: profileIdFromUrl(c.author_url, "zhihu"),
      parent_comment_id: c.parent_comment_id || "",
      native_comment_id: c.native_comment_id || "",
      native_parent_id: c.native_parent_id || "",
      comment_url: c.comment_url || "",
      source_type: c.source_type || "comment",
      published_at_raw: c.published_at_raw || "",
      likes: c.likes,
      source_keyword: keyword,
      create_time: parseDisplayedTime(c.published_at_raw)?.toISOString() || ""
      }));
    comments.push(...itemComments);

    console.log(`  -> Extracted: "${contentRecord.title.slice(0, 30)}..." | ${itemComments.length} comments`);
  } catch (err) {
    console.error(`  -> Failed fetching ${item.url}:`, err.message);
  }
}

// Write JSONL
const contentsFile = path.join(outputDir, "zhihu_contents.jsonl");
const commentsFile = path.join(outputDir, "zhihu_comments.jsonl");

await fs.writeFile(
  contentsFile,
  contents.map(c => JSON.stringify(c)).join("\n") + "\n",
  "utf-8"
);
await fs.writeFile(
  commentsFile,
  comments.map(c => JSON.stringify(c)).join("\n") + "\n",
  "utf-8"
);

console.log(`[ZhihuCrawler] Successfully saved:`);
console.log(`  - Contents: ${contents.length} -> ${contentsFile}`);
console.log(`  - Comments: ${comments.length} -> ${commentsFile}`);

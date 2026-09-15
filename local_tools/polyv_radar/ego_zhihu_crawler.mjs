import fs from 'node:fs/promises';
import path from 'node:path';
import { filterSearchResults, loadUntilStable, profileIdFromUrl, waitForResults } from './ego_helpers.mjs';

const args = process.argv.slice(2);
const keyword = process.env.KEYWORD || args[0] || "员工培训";
const maxContents = parseInt(process.env.MAX_CONTENTS || args[1] || "5", 10);
const maxComments = parseInt(process.env.MAX_COMMENTS || args[2] || "10", 10);
const outputDir = process.env.OUTPUT_DIR || args[3] || `/Users/sexpistole111/Documents/workplace/polyv-radar-data/raw/20260914-zhihu/zhihu/${keyword}`;

await fs.mkdir(outputDir, { recursive: true });

let task;
try {
  task = await takeOverTaskSpace(8);
} catch (e) {
  try {
    task = await taskSpace(8);
  } catch (err) {
    task = await taskSpace("zhihu ego scraper");
  }
}

const page = task.page("p1");

console.log(`[ZhihuCrawler] Searching Zhihu for "${keyword}" (max ${maxContents} items)...`);
const searchUrl = `https://www.zhihu.com/search?type=content&q=${encodeURIComponent(keyword)}`;
await page.goto(searchUrl);
await page.waitForLoadState({ timeout: 15000 }).catch(() => {});
await waitForResults(page, '.SearchResult-Card, [class*="SearchResult-Card"], .Card, .ContentItem');

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
    await loadUntilStable(page, '.CommentItemV2, .CommentItem, [class*="CommentItem"]', maxComments);

    const pageData = await page.evaluate(() => {
      const titleEl = document.querySelector('h1, .QuestionHeader-title');
      const richTextEl = document.querySelector('.RichContent-inner, .RichText, .Post-RichText');
      const authorLink = document.querySelector('a[href*="/people/"]');
      const authorEl = authorLink || document.querySelector('.AuthorInfo-name');
      const tags = Array.from(document.querySelectorAll('.QuestionHeader-topics .Tag, a[href*="/topic/"]')).map(a => a.innerText.trim());

      // Try reading comments if already open
      const commentNodes = document.querySelectorAll('.CommentItemV2, .CommentItem, [class*="CommentItem"]');
      const parsedComments = [];
      for (let idx = 0; idx < commentNodes.length; idx++) {
        const el = commentNodes[idx];
        const authorLink = el.querySelector('a[href*="/people/"]');
        const author = authorLink?.innerText?.trim() || el.querySelector('.UserLink-link, [class*="author"]')?.innerText?.trim() || "知乎用户";
        const text = el.querySelector('.CommentItemV2-content, [class*="content"]')?.innerText?.trim() || "";
        if (text) {
          parsedComments.push({
            comment_id: `zh_cm_${idx}_${Date.now()}`,
            author,
            author_url: authorLink?.href || "",
            parent_comment_id: el.getAttribute('data-parent-id') || "",
            text,
            likes: 0
          });
        }
      }

      return {
        title: titleEl ? titleEl.innerText.trim() : "",
        text: richTextEl ? richTextEl.innerText.trim() : "",
        author: authorEl ? authorEl.innerText.trim() : "",
        author_url: authorLink?.href || "",
        tags,
        comments: parsedComments
      };
    });

    const matchId = item.url.match(/\/(?:question\/\d+\/answer|p|question)\/(\d+)/);
    const contentId = matchId ? matchId[1] : `zh_${i}_${Date.now()}`;

    const contentRecord = {
      platform: "zhihu",
      content_id: contentId,
      title: pageData.title || item.title || "知乎问答",
      text: (pageData.text || item.text || item.title).slice(0, 1500),
      url: item.url,
      author: pageData.author || item.author || "知乎答主",
      author_url: pageData.author_url || "",
      author_id: profileIdFromUrl(pageData.author_url, "zhihu"),
      tags: pageData.tags,
      source_keyword: keyword,
      create_time: new Date().toISOString()
    };
    contents.push(contentRecord);

    const itemComments = pageData.comments.slice(0, maxComments).map(c => ({
      platform: "zhihu",
      comment_id: `${contentId}_${c.comment_id}`,
      content_id: contentId,
      text: c.text,
      author: c.author,
      author_url: c.author_url || "",
      author_id: profileIdFromUrl(c.author_url, "zhihu"),
      parent_comment_id: c.parent_comment_id || "",
      likes: c.likes,
      source_keyword: keyword,
      create_time: new Date().toISOString()
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

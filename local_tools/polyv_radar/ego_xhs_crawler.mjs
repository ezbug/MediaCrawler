import fs from 'node:fs/promises';
import path from 'node:path';
import { filterSearchResults, loadUntilStable, profileIdFromUrl } from './ego_helpers.mjs';

// Support env vars or CLI arguments
const args = process.argv.slice(2);
const keyword = process.env.KEYWORD || args[0] || "员工培训";
const maxContents = parseInt(process.env.MAX_CONTENTS || args[1] || "5", 10);
const maxComments = parseInt(process.env.MAX_COMMENTS || args[2] || "10", 10);
const outputDir = process.env.OUTPUT_DIR || args[3] || `/Users/sexpistole111/Documents/workplace/polyv-radar-data/raw/20260914-083100/xhs/${keyword}`;

await fs.mkdir(outputDir, { recursive: true });

let task;
try {
  task = await takeOverTaskSpace(8);
} catch (e) {
  try {
    task = await taskSpace(8);
  } catch (err) {
    task = await taskSpace("xhs ego scraper");
  }
}

const page = task.page("p1");

console.log(`[XhsCrawler] Searching Xiaohongshu for "${keyword}" (max ${maxContents} notes)...`);
const searchUrl = `https://www.xiaohongshu.com/search_result?keyword=${encodeURIComponent(keyword)}`;
await page.goto(searchUrl);
await page.waitForLoadState({ timeout: 15000 }).catch(() => {});
await page.waitForSelector('a[href*="/search_result/"]', { timeout: 20000 }).catch(() => {});
await new Promise(r => setTimeout(r, 4000));

// Extract note links with xsec_token
const candidateNotes = await page.evaluate(() => {
  const results = [];
  // Must match search_result with note id and xsec_token
  const links = Array.from(document.querySelectorAll('a[href*="/search_result/"]'));
  for (const a of links) {
    const href = a.href;
    const match = href.match(/\/search_result\/([a-zA-Z0-9]+)/);
    if (!match || !href.includes("xsec_token=")) continue;
    const id = match[1];
    if (results.some(r => r.id === id)) continue;

    const title = a.innerText.trim().replace(/\n+/g, " ");
    let container = a.parentElement;
    let snippet = title;
    for (let i = 0; i < 5 && container; i++, container = container.parentElement) {
      const text = (container.innerText || "").trim().replace(/\n+/g, " ");
      if (text.length > 900) break;
      if (text.length > snippet.length) snippet = text;
    }

    results.push({
      id,
      url: href,
      title,
      searchText: title,
      rawSnippet: snippet.slice(0, 500)
    });
  }
  return results;
});

const relevantNotes = filterSearchResults(keyword, candidateNotes);
const targetNotes = relevantNotes.slice(0, maxContents);
console.log(`[XhsCrawler] Found ${candidateNotes.length} raw candidates with token, ${relevantNotes.length} relevant, selected ${targetNotes.length} notes.`);
if (relevantNotes.length === 0) {
  console.error(`[XhsCrawler] No relevant note candidates found for "${keyword}".`);
  process.exitCode = 2;
}

const contents = [];
const comments = [];

for (let i = 0; i < targetNotes.length; i++) {
  const n = targetNotes[i];
  console.log(`[XhsCrawler] (${i + 1}/${targetNotes.length}) Fetching note: ${n.id} -> ${n.url}`);
  try {
    await page.goto(n.url);
    await page.waitForLoadState({ timeout: 15000 }).catch(() => {});
    await new Promise(r => setTimeout(r, 3500));
    await loadUntilStable(page, '.parent-comment, .comment-item', maxComments);

    const pageData = await page.evaluate(() => {
      const titleEl = document.querySelector('#detail-title, .title, [class*="note-title"]');
      const descEl = document.querySelector('#detail-desc, [class*="desc"], [class*="note-text"]');
      const authorLink = document.querySelector('.author-container a, a[href*="/user/profile/"]');
      const authorEl = authorLink || document.querySelector('.author-container, .name, [class*="author"]');
      const tags = Array.from(document.querySelectorAll('a[href*="/tag/"], a[href*="/search/"]'))
        .map(a => a.innerText.trim())
        .filter(t => t.startsWith('#'));

      const commentNodes = document.querySelectorAll('.parent-comment, .comment-item');
      const parsedComments = [];
      const seenComments = new Set();
      for (let idx = 0; idx < commentNodes.length; idx++) {
        const el = commentNodes[idx];
        const lines = el.innerText.split('\n').map(s => s.trim()).filter(Boolean);
        if (lines.length < 2) continue;
        const authorLink = el.querySelector('a[href*="/user/profile/"]');
        const author = authorLink?.innerText?.trim() || lines[0];
        let text = lines[1];
        if (text === '作者' && lines.length > 2) text = lines[2];

        // Deduplicate identical author+text
        const key = `${author}:${text}`;
        if (seenComments.has(key)) continue;
        seenComments.add(key);

        let likes = 0;
        for (const l of lines) {
          if (/^\d+$/.test(l)) {
            likes = parseInt(l, 10);
            break;
          }
        }

        parsedComments.push({
          comment_id: `xhs_cm_${idx}_${Date.now()}`,
          author,
          author_url: authorLink?.href || "",
          parent_comment_id: el.getAttribute('data-parent-id') || "",
          text,
          likes
        });
      }

      return {
        title: titleEl ? titleEl.innerText.trim() : "",
        desc: descEl ? descEl.innerText.trim() : "",
        author: authorEl ? authorEl.innerText.split('\n')[0].trim() : "小红书用户",
        author_url: authorLink?.href || "",
        tags,
        comments: parsedComments
      };
    });

    const contentRecord = {
      platform: "xhs",
      content_id: n.id,
      title: pageData.title || n.title || "小红书笔记",
      text: (pageData.desc || pageData.title || n.title),
      url: `https://www.xiaohongshu.com/explore/${n.id}`,
      author: pageData.author || "小红书创作者",
      author_url: pageData.author_url || "",
      author_id: profileIdFromUrl(pageData.author_url, "xhs"),
      tags: pageData.tags,
      source_keyword: keyword,
      create_time: new Date().toISOString()
    };
    contents.push(contentRecord);

    const noteComments = pageData.comments.slice(0, maxComments).map(c => ({
      platform: "xhs",
      comment_id: `${n.id}_${c.comment_id}`,
      content_id: n.id,
      text: c.text,
      author: c.author,
      author_url: c.author_url || "",
      author_id: profileIdFromUrl(c.author_url, "xhs"),
      parent_comment_id: c.parent_comment_id || "",
      likes: c.likes,
      source_keyword: keyword,
      create_time: new Date().toISOString()
    }));
    comments.push(...noteComments);

    console.log(`  -> Extracted: "${contentRecord.title.slice(0, 30)}..." | ${noteComments.length} comments`);
  } catch (err) {
    console.error(`  -> Failed fetching note ${n.id}:`, err.message);
  }
}

// Write JSONL
const contentsFile = path.join(outputDir, "xhs_contents.jsonl");
const commentsFile = path.join(outputDir, "xhs_comments.jsonl");

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

console.log(`[XhsCrawler] Successfully saved:`);
console.log(`  - Contents: ${contents.length} -> ${contentsFile}`);
console.log(`  - Comments: ${comments.length} -> ${commentsFile}`);

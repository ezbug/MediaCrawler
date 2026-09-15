import fs from 'node:fs/promises';
import path from 'node:path';
import { filterSearchResults, loadUntilStable, profileIdFromUrl } from './ego_helpers.mjs';

const args = process.argv.slice(2);
const keyword = process.env.KEYWORD || args[0] || "员工培训";
const maxContents = parseInt(process.env.MAX_CONTENTS || args[1] || "5", 10);
const maxComments = parseInt(process.env.MAX_COMMENTS || args[2] || "10", 10);
const outputDir = process.env.OUTPUT_DIR || args[3] || `/Users/sexpistole111/Documents/workplace/polyv-radar-data/raw/20260914-bili/bili/${keyword}`;

await fs.mkdir(outputDir, { recursive: true });

let task;
try {
  task = await takeOverTaskSpace(8);
} catch (e) {
  try {
    task = await taskSpace(8);
  } catch (err) {
    task = await taskSpace("bili ego scraper");
  }
}

const page = task.page("p1");

console.log(`[BiliCrawler] Searching Bilibili for "${keyword}" (max ${maxContents} videos)...`);
const searchUrl = `https://search.bilibili.com/all?keyword=${encodeURIComponent(keyword)}`;
await page.goto(searchUrl);
await page.waitForLoadState({ timeout: 15000 }).catch(() => {});
await page.waitForSelector('a[href*="/video/BV"]', { timeout: 20000 }).catch(() => {});
await new Promise(r => setTimeout(r, 4000));

const candidateVideos = await page.evaluate(() => {
  const links = Array.from(document.querySelectorAll('a[href*="/video/BV"]'));
  const seen = new Set();
  const list = [];
  for (const a of links) {
    const href = a.href;
    const match = href.match(/\/video\/(BV[a-zA-Z0-9]+)/);
    if (!match) continue;
    const bvid = match[1];
    if (seen.has(bvid)) continue;
    seen.add(bvid);
    
    // Title is usually inside title attribute or card info
    const title = a.getAttribute("title") || a.innerText.trim().replace(/\n+/g, " ");
    let container = a.parentElement;
    let snippet = title;
    for (let i = 0; i < 5 && container; i++, container = container.parentElement) {
      const text = (container.innerText || "").trim().replace(/\n+/g, " ");
      if (text.length > 900) break;
      if (text.length > snippet.length) snippet = text;
    }
    list.push({
      bvid,
      url: `https://www.bilibili.com/video/${bvid}/`,
      title,
      rawSnippet: snippet.slice(0, 500)
    });
  }
  return list;
});

const relevantVideos = filterSearchResults(keyword, candidateVideos);
const targetVideos = relevantVideos.slice(0, maxContents);
console.log(`[BiliCrawler] Found ${candidateVideos.length} raw candidates, ${relevantVideos.length} relevant, selected ${targetVideos.length} videos.`);
if (relevantVideos.length === 0) {
  console.error(`[BiliCrawler] No relevant video candidates found for "${keyword}".`);
  process.exitCode = 2;
}

const contents = [];
const comments = [];

for (let i = 0; i < targetVideos.length; i++) {
  const v = targetVideos[i];
  console.log(`[BiliCrawler] (${i + 1}/${targetVideos.length}) Fetching video: ${v.bvid}`);
  try {
    await page.goto(v.url);
    await page.waitForLoadState({ timeout: 15000 }).catch(() => {});
    await new Promise(r => setTimeout(r, 2500));

    await page.evaluate(() => window.scrollBy(0, 1200));
    await new Promise(r => setTimeout(r, 3500));
    await loadUntilStable(page, 'bili-comments bili-comment-thread-renderer', maxComments);

    const pageData = await page.evaluate(() => {
      const titleEl = document.querySelector('h1, .video-title, [class*="video-title"]');
      const descEl = document.querySelector('.basic-desc-info, .desc-info-text, [class*="desc"]');
      const upLink = document.querySelector('a[href*="space.bilibili.com"]');
      const upEl = upLink || document.querySelector('.up-name, .up-info__name');
      const tags = Array.from(document.querySelectorAll('.tag-link, a[href*="/tag/"]')).map(a => a.innerText.trim());

      const c = document.querySelector('bili-comments');
      const threads = c?.shadowRoot?.querySelectorAll('bili-comment-thread-renderer') || [];
      const parsedComments = [];
      for (let idx = 0; idx < threads.length; idx++) {
        const t = threads[idx];
        const comment = t.shadowRoot?.querySelector('#comment');
        if (!comment || !comment.shadowRoot) continue;

        const userInfo = comment.shadowRoot.querySelector('bili-comment-user-info');
        const user = userInfo?.shadowRoot?.querySelector('#user-name')?.innerText || "B站用户";

        const richText = comment.shadowRoot.querySelector('bili-rich-text');
        const text = richText?.shadowRoot?.querySelector('#contents')?.innerText || richText?.innerText || "";

        parsedComments.push({
          comment_id: `bili_cm_${idx}_${Date.now()}`,
          author: user.trim(),
          author_url: userInfo?.shadowRoot?.querySelector('a[href*="space.bilibili.com"]')?.href || "",
          text: text.trim(),
          likes: 0
        });
      }

      return {
        title: titleEl ? titleEl.innerText.trim() : "",
        desc: descEl ? descEl.innerText.trim() : "",
        author: upEl ? upEl.innerText.trim() : "B站创作者",
        author_url: upLink?.href || "",
        tags,
        comments: parsedComments
      };
    });

    const contentRecord = {
      platform: "bili",
      content_id: v.bvid,
      title: pageData.title || v.title || "B站视频",
      text: pageData.desc || pageData.title || v.title,
      url: v.url,
      author: pageData.author || "B站创作者",
      author_url: pageData.author_url || "",
      author_id: profileIdFromUrl(pageData.author_url, "bili"),
      tags: pageData.tags,
      source_keyword: keyword,
      create_time: new Date().toISOString()
    };
    contents.push(contentRecord);

    const videoComments = pageData.comments.slice(0, maxComments).map(c => ({
      platform: "bili",
      comment_id: `${v.bvid}_${c.comment_id}`,
      content_id: v.bvid,
      text: c.text,
      author: c.author,
      author_url: c.author_url || "",
      author_id: profileIdFromUrl(c.author_url, "bili"),
      likes: c.likes,
      source_keyword: keyword,
      create_time: new Date().toISOString()
    }));
    comments.push(...videoComments);

    console.log(`  -> Extracted: "${contentRecord.title.slice(0, 30)}..." | ${videoComments.length} comments`);
  } catch (err) {
    console.error(`  -> Failed fetching video ${v.bvid}:`, err.message);
  }
}

// Write JSONL
const contentsFile = path.join(outputDir, "bili_contents.jsonl");
const commentsFile = path.join(outputDir, "bili_comments.jsonl");

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

console.log(`[BiliCrawler] Successfully saved:`);
console.log(`  - Contents: ${contents.length} -> ${contentsFile}`);
console.log(`  - Comments: ${comments.length} -> ${commentsFile}`);

import fs from 'node:fs/promises';
import path from 'node:path';
import { cardTitleFromText, filterSearchResults, loadUntilStable, profileIdFromUrl } from './ego_helpers.mjs';

const args = process.argv.slice(2);
const keyword = process.env.KEYWORD || args[0] || "企业直播平台推荐";
const maxContents = parseInt(process.env.MAX_CONTENTS || args[1] || "5", 10);
const maxComments = parseInt(process.env.MAX_COMMENTS || args[2] || "10", 10);
const outputDir = process.env.OUTPUT_DIR || args[3] || `/Users/sexpistole111/Documents/workplace/polyv-radar-data/raw/test/dy/${keyword}`;

await fs.mkdir(outputDir, { recursive: true });

let task;
try {
  task = await takeOverTaskSpace(8);
} catch (e) {
  try {
    task = await taskSpace(8);
  } catch (err) {
    task = await taskSpace("douyin ego scraper");
  }
}

const page = task.page("p1");

console.log(`[EgoCrawler] Searching Douyin for "${keyword}" (max ${maxContents} videos)...`);
const searchUrl = `https://www.douyin.com/search/${encodeURIComponent(keyword)}?type=video`;
await page.goto('https://www.douyin.com/');
await page.waitForLoadState({ timeout: 15000 }).catch(() => {});
await page.waitForTimeout(1500);
await page.goto(searchUrl);
await page.waitForLoadState({ timeout: 15000 }).catch(() => {});
await page.waitForSelector('a[href*="/video/"]', { timeout: 20000 }).catch(() => {});
await page.waitForTimeout(10000);

// Extract search results
const rawCandidateVideos = await page.evaluate(() => {
  const results = [];
  const links = Array.from(document.querySelectorAll('a[href*="/video/"]'));
  for (const a of links) {
    const href = a.href;
    const match = href.match(/\/video\/(\d+)/);
    if (!match) continue;
    const id = match[1];
    if (results.some(r => r.id === id)) continue;

    const cardText = a.innerText || "";
    let container = a.parentElement;
    let snippet = cardText;
    for (let i = 0; i < 5 && container; i++, container = container.parentElement) {
      const text = (container.innerText || "").trim().replace(/\n+/g, " ");
      if (text.length > 900) break;
      if (text.length > snippet.length) snippet = text;
    }

    results.push({
      id,
      url: `https://www.douyin.com/video/${id}`,
      cardText,
      rawSnippet: snippet.slice(0, 500)
    });
  }
  return results;
});

const candidateVideos = rawCandidateVideos.map((video) => {
  const title = cardTitleFromText(video.cardText);
  return {
    id: video.id,
    url: video.url,
    title: title || video.cardText.trim().replace(/\n+/g, " "),
    searchText: title || video.cardText.trim().replace(/\n+/g, " "),
    rawSnippet: video.rawSnippet,
  };
});

const relevantVideos = filterSearchResults(keyword, candidateVideos);
const targetVideos = relevantVideos.slice(0, maxContents);
console.log(`[EgoCrawler] Found ${candidateVideos.length} raw candidates, ${relevantVideos.length} relevant, selected ${targetVideos.length} videos.`);
if (relevantVideos.length === 0) {
  console.error(`[EgoCrawler] No relevant video candidates found for "${keyword}".`);
  process.exitCode = 2;
}

const contents = [];
const comments = [];

for (let i = 0; i < targetVideos.length; i++) {
  const v = targetVideos[i];
  console.log(`[EgoCrawler] (${i + 1}/${targetVideos.length}) Fetching video: ${v.url}`);
  try {
    await page.goto(v.url);
    await page.waitForLoadState({ timeout: 15000 }).catch(() => {});
    await new Promise(r => setTimeout(r, 3500));
    await page.waitForSelector('h1, [data-e2e="video-desc"]', { timeout: 15000 }).catch(() => {});
    await loadUntilStable(page, '[data-e2e="comment-item"]', maxComments);

    const pageData = await page.evaluate(() => {
      const descEl = document.querySelector('h1, [data-e2e="video-desc"]');
      const infoLinks = Array.from(document.querySelectorAll('[data-e2e="user-info"] a[href*="/user/"]'));
      const authorLink = infoLinks.find(link => (link.innerText || '').trim()) || infoLinks[0] || document.querySelector('a[href*="/user/"]:not([href*="/user/self"])');
      const authorEl = authorLink || document.querySelector('[data-e2e="user-info"] span, [class*="author"]');
      const tags = Array.from(document.querySelectorAll('a[href*="/tag/"], a[href*="/search/"]'))
        .map(a => a.innerText.trim())
        .filter(t => t.startsWith('#'));

      // Extract comment items
      const commentItems = document.querySelectorAll('[data-e2e="comment-item"]');
      const parsedComments = [];
      for (let idx = 0; idx < commentItems.length; idx++) {
        const el = commentItems[idx];
        const lines = el.innerText.split('\n').map(s => s.trim()).filter(Boolean);
        const authorLink = el.querySelector('a[href*="/user/"]');
        const author = authorLink?.innerText?.trim() || lines[0] || "";
        let text = lines[1] || "";
        if (text === '...' && lines.length > 2) text = lines[2];
        if (text === '作者' && lines.length > 3) text = lines[3];

        let likes = 0;
        for (const l of lines) {
          if (/^\d+$/.test(l)) {
            likes = parseInt(l, 10);
            break;
          }
        }

        parsedComments.push({
          comment_id: `cm_${idx}_${Date.now()}`,
          author,
          author_url: authorLink?.href || "",
          parent_comment_id: el.getAttribute('data-parent-id') || "",
          text,
          likes
        });
      }

      return {
        title: document.title.replace(/ - 抖音$/, "").trim(),
        desc: descEl ? descEl.innerText.trim() : "",
        author: authorEl ? authorEl.innerText.trim() : "",
        author_url: authorLink?.href || "",
        tags,
        comments: parsedComments
      };
    });

    const contentRecord = {
      platform: "dy",
      content_id: v.id,
      title: pageData.desc || pageData.title || v.title,
      text: pageData.desc || v.rawSnippet || pageData.title,
      url: v.url,
      author: pageData.author || "抖音创作者",
      author_url: pageData.author_url || "",
      author_id: profileIdFromUrl(pageData.author_url, "dy"),
      tags: pageData.tags,
      source_keyword: keyword,
      create_time: new Date().toISOString()
    };
    contents.push(contentRecord);

    const videoComments = pageData.comments.slice(0, maxComments).map(c => ({
      platform: "dy",
      comment_id: `${v.id}_${c.comment_id}`,
      content_id: v.id,
      text: c.text,
      author: c.author,
      author_url: c.author_url || "",
      author_id: profileIdFromUrl(c.author_url, "dy"),
      parent_comment_id: c.parent_comment_id || "",
      likes: c.likes,
      source_keyword: keyword,
      create_time: new Date().toISOString()
    }));
    comments.push(...videoComments);

    console.log(`  -> Extracted: "${contentRecord.title.slice(0, 30)}..." | ${videoComments.length} comments`);
  } catch (err) {
    console.error(`  -> Failed fetching video ${v.id}:`, err.message);
  }
}

// Write JSONL
const contentsFile = path.join(outputDir, "dy_videos.jsonl");
const commentsFile = path.join(outputDir, "dy_comments.jsonl");

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

console.log(`[EgoCrawler] Successfully saved:`);
console.log(`  - Contents: ${contents.length} -> ${contentsFile}`);
console.log(`  - Comments: ${comments.length} -> ${commentsFile}`);

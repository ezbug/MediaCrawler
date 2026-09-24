import fs from 'node:fs/promises';
import path from 'node:path';
import { filterSearchResults, isExpectedXhsNoteUrl, loadUntilStable, parseDisplayedTime, profileIdFromUrl, waitForResults, xhsDetailReady } from './ego_helpers.mjs';

// Support env vars or CLI arguments
const args = process.argv.slice(2);
const keyword = process.env.KEYWORD || args[0] || "员工培训";
const maxContents = parseInt(process.env.MAX_CONTENTS || args[1] || "5", 10);
const maxComments = parseInt(process.env.MAX_COMMENTS || args[2] || "10", 10);
const outputDir = process.env.OUTPUT_DIR || args[3] || `/Users/sexpistole111/Documents/workplace/polyv-radar-data/raw/20260914-083100/xhs/${keyword}`;

await fs.mkdir(outputDir, { recursive: true });

const taskspaceId = Number(process.env.POLYV_TASKSPACE_ID);
if (!Number.isInteger(taskspaceId) || taskspaceId <= 0) throw new Error('需要有效的 POLYV_TASKSPACE_ID');
const task = await taskSpace(taskspaceId);

const page = task.page("p1");

console.log(`[XhsCrawler] Searching Xiaohongshu for "${keyword}" (max ${maxContents} notes)...`);
const searchUrl = `https://www.xiaohongshu.com/search_result?keyword=${encodeURIComponent(keyword)}`;
await page.goto(searchUrl);
await page.waitForLoadState({ timeout: 15000 }).catch(() => {});
await waitForResults(page, 'a[href*="/search_result/"]');

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
    const detailDeadline = Date.now() + 15000;
    let detailReady = false;
    while (Date.now() < detailDeadline) {
      const state = await page.evaluate(() => ({
        path: window.location.pathname,
        title: document.querySelector('#detail-title')?.innerText?.trim() || '',
        authorHref: document.querySelector('#noteContainer .author-container a[href*="/user/profile/"], #noteContainer .author-wrapper a[href*="/user/profile/"]')?.href || '',
      }));
      if (xhsDetailReady(state, n)) {
        detailReady = true;
        break;
      }
      await page.waitForTimeout(250);
    }
    if (!detailReady) {
      console.error(`  -> Detail page did not become ready for ${n.id}; skipped.`);
      continue;
    }
    await page.waitForSelector('#noteContainer .author-container a[href*="/user/profile/"], #noteContainer .author-wrapper a[href*="/user/profile/"], #noteContainer .name', { timeout: 5000 }).catch(() => {});
    const detailUrl = await page.url();
    if (!isExpectedXhsNoteUrl(detailUrl, n.id)) {
      console.error(`  -> Skipped redirected note ${n.id}; final URL: ${detailUrl}`);
      continue;
    }
    await loadUntilStable(page, '.parent-comment, .comment-item', maxComments, 2, 14, 300);

    const pageData = await page.evaluate(() => {
      const titleEl = document.querySelector('#detail-title');
      const descEl = document.querySelector('#detail-desc');
      const noteContainer = document.querySelector('#noteContainer') || document;
      const authorContainer = noteContainer.querySelector('.author-container, .author-wrapper');
      const authorLink = authorContainer?.querySelector('a[href*="/user/profile/"]') || null;
      const authorEl = authorContainer?.querySelector('.name, .username') || authorContainer;
      const tags = Array.from(document.querySelectorAll('a[href*="/tag/"], a[href*="/search/"]'))
        .map(a => a.innerText.trim())
        .filter(t => t.startsWith('#'));

      // Read the actual comment nodes once. The outer .parent-comment wrapper
      // also contains replies, so treating it as a comment loses author/id
      // information and makes parent-child targeting unreliable.
      const commentNodes = document.querySelectorAll('.comments-container .comment-item');
      const parsedComments = [];
      const seenComments = new Set();
      for (let idx = 0; idx < commentNodes.length; idx++) {
        const el = commentNodes[idx];
        const lines = el.innerText.split('\n').map(s => s.trim()).filter(Boolean);
        if (lines.length < 2) continue;
        const authorLink = el.querySelector('.author .name, a[href*="/user/profile/"]');
        const author = authorLink?.innerText?.trim() || lines[0];
        const contentEl = el.querySelector('.content .note-text, .content');
        let text = contentEl?.innerText?.trim() || lines[1];
        if (text === '作者' && lines.length > 2) text = lines[2];
        const publishedAtRaw = [...lines].reverse().find(line => /刚刚|刚才|今天|昨天|\d+\s*(秒|分钟|小时|天|周|月|个月|年)前|20\d{2}[-/.]\d{1,2}[-/.]\d{1,2}/.test(line)) || "";
        const nativeCommentId = el.getAttribute('data-comment-id') || el.getAttribute('data-cid') || el.getAttribute('data-id') || el.id?.replace(/^comment-/, '') || "";
        const parentWrapper = el.closest('.parent-comment');
        const rootNode = parentWrapper?.querySelector(':scope > .comment-item:not(.comment-item-sub)');
        const rootId = rootNode?.getAttribute('data-comment-id') || rootNode?.getAttribute('data-cid') || rootNode?.getAttribute('data-id') || rootNode?.id?.replace(/^comment-/, '') || "";
        const isReply = el.classList.contains('comment-item-sub');
        const nativeParentId = el.getAttribute('data-root-id') || el.getAttribute('data-parent-id') || (isReply ? rootId : "");
        const commentBaseUrl = location.href.split('#')[0];
        const commentUrl = nativeCommentId ? `${commentBaseUrl}#comment-${nativeCommentId}` : "";

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
          native_comment_id: nativeCommentId,
          native_parent_id: nativeParentId,
          comment_url: commentUrl,
          source_type: nativeParentId ? "reply" : "comment",
          published_at_raw: publishedAtRaw,
          author,
          author_url: authorLink?.href || "",
          parent_comment_id: nativeParentId,
          text,
          likes
        });
      }

      return {
        title: titleEl ? titleEl.innerText.trim() : "",
        desc: descEl ? descEl.innerText.trim() : "",
        author: authorEl ? authorEl.innerText.split('\n')[0].trim() : "小红书用户",
        author_url: authorLink?.href || "",
        page_url: location.href,
        tags,
        comments: parsedComments
      };
    });

    if (!pageData.title) {
      console.error(`  -> Skipped note ${n.id}; detail title was not available.`);
      continue;
    }

    const contentRecord = {
      platform: "xhs",
      content_id: n.id,
      title: pageData.title || n.title || "小红书笔记",
      text: (pageData.desc || pageData.title || n.title),
      // XHS detail pages require the short-lived xsec_token for a later
      // Ego Lite re-open. Keep the exact navigated URL for evidence checks.
      url: pageData.page_url || detailUrl,
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
      comment_id: `${n.id}_${c.native_comment_id || c.comment_id}`,
      content_id: n.id,
      text: c.text,
      author: c.author,
      author_url: c.author_url || "",
      author_id: profileIdFromUrl(c.author_url, "xhs"),
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

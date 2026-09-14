import fs from 'node:fs/promises';
import { profileIdFromUrl } from './ego_helpers.mjs';

const inputPath = process.env.POLYV_PROFILE_INPUT;
const outputPath = process.env.POLYV_PROFILE_OUTPUT;
const candidates = JSON.parse(await fs.readFile(inputPath, 'utf-8'));

let task;
try {
  task = await takeOverTaskSpace(8);
} catch (error) {
  task = await taskSpace(8).catch(() => taskSpace('polyv profile enricher'));
}
const page = task.page('p1');
const profiles = [];

for (const candidate of candidates) {
  if (!candidate.profile_url || !candidate.author_id) continue;
  try {
    await page.goto(candidate.profile_url);
    await page.waitForLoadState({ timeout: 15000 }).catch(() => {});
    await page.waitForSelector('body', { timeout: 15000 }).catch(() => {});
    await page.waitForSelector('a[href*="/video/"], a[href*="/explore/"], a[href*="/question/"], a[href*="/p/"]', { timeout: 10000 }).catch(() => {});
    await new Promise(resolve => setTimeout(resolve, 2500));
    const data = await page.evaluate(() => {
      const body = document.body?.innerText || '';
      const display = document.querySelector('h1, [class*="user-name"], [class*="nickname"], [class*="name"]')?.innerText?.trim() || '';
      const postLinks = Array.from(document.querySelectorAll('a[href*="/video/"], a[href*="/explore/"], a[href*="/question/"], a[href*="/p/"]'));
      const seen = new Set();
      const posts = [];
      for (const link of postLinks) {
        const url = link.href.split('?')[0];
        if (!url || seen.has(url)) continue;
        seen.add(url);
        posts.push({
          post_id: url.split('/').filter(Boolean).pop() || url,
          url,
          title: (link.getAttribute('title') || link.innerText || '').trim().replace(/\s+/g, ' ').slice(0, 240),
          text: (link.parentElement?.innerText || link.innerText || '').trim().replace(/\s+/g, ' ').slice(0, 500),
          published_at: '',
        });
        if (posts.length >= 5) break;
      }
      return { available: Boolean(body.trim()), display_name: display, bio: body.slice(0, 2000), verified: /认证|verified|官方/.test(body), posts };
    });
    profiles.push({
      run_id: candidate.run_id,
      platform: candidate.platform,
      author_id: candidate.author_id || profileIdFromUrl(candidate.profile_url, candidate.platform),
      author_url: candidate.profile_url,
      display_name: data.display_name,
      bio: data.bio,
      verified: data.verified,
      available: data.available,
      posts: data.posts,
    });
  } catch (error) {
    profiles.push({
      run_id: candidate.run_id,
      platform: candidate.platform,
      author_id: candidate.author_id,
      author_url: candidate.profile_url,
      available: false,
      error: String(error?.message || error),
      posts: [],
    });
  }
}

await fs.writeFile(outputPath, JSON.stringify({ profiles }, null, 2), 'utf-8');
console.log(`[ProfileEnricher] saved ${profiles.length} profiles to ${outputPath}`);

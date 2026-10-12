/**
 * Read-only Xiaohongshu note check: extract OUR comment threads from the
 * note's native state (window.__INITIAL_STATE__) including sub-replies.
 *
 * Params come from /tmp/polyv_xhs_note_params.json:
 *   {"task": 2, "url": "https://...", "own": "小馨的ZigoAi", "page": "p1"}
 *
 * Prints one JSON line. Never types, clicks a submit control, or posts.
 */

const fs = await import("node:fs/promises");
let params = {};
try {
  params = JSON.parse(await fs.readFile("/tmp/polyv_xhs_note_params.json", "utf8"));
} catch {
  params = {};
}

const result = { url: params.url || "", ok: false, ourThreads: [] };

try {
  if (!params.task || !params.url) throw new Error("params file needs task and url");
  const task = await taskSpace(Number(params.task));
  const page = task.page(params.page || "p1");
  await page.goto(params.url);
  await page.waitForTimeout(7000);
  result.ourThreads = await page.evaluate((ownName) => {
    const state = window.__INITIAL_STATE__;
    const map = state && state.note && state.note.noteDetailMap;
    const entry = map ? map[Object.keys(map)[0]] : null;
    const comments = (entry && entry.comments && entry.comments.list) || [];
    const noteAuthor = entry && entry.note && entry.note.user ? entry.note.user.nickname : "";
    const out = [];
    for (const c of comments) {
      const subs = (c.subComments || []).map((s) => ({
        author: s.userInfo ? s.userInfo.nickname : "",
        text: (s.content || "").slice(0, 220),
        time: s.createTime,
        sub2: (s.subComments || []).map((x) => ({
          author: x.userInfo ? x.userInfo.nickname : "",
          text: (x.content || "").slice(0, 220),
          time: x.createTime,
        })),
      }));
      const ours = (c.userInfo && c.userInfo.nickname) === ownName;
      const touchesUs = subs.some(
        (s) => s.author === ownName || (s.sub2 || []).some((x) => x.author === ownName),
      );
      if (ours || touchesUs) {
        out.push({
          noteAuthor,
          ourComment: {
            author: c.userInfo ? c.userInfo.nickname : "",
            text: (c.content || "").slice(0, 220),
            time: c.createTime,
          },
          subs,
        });
      }
    }
    return out;
  }, params.own || "");
  result.ok = true;
} catch (error) {
  result.error = String((error && error.message) || error).slice(0, 200);
}

console.log("XHSNOTE " + JSON.stringify(result).slice(0, 4000));

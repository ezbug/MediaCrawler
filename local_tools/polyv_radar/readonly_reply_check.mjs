/**
 * Read-only reply check for the Ego Lite reply-inspection TaskSpace.
 *
 * Runs inside the ego-browser node runtime. Opens one target page, expands
 * reply threads, scrolls the comment list a bounded number of rounds, and
 * prints ONE JSON line describing:
 *
 * - our own comments on the page (author matches OWN_ACCOUNT)
 * - whether any of them carries a reply indicator ("展开N条回复")
 * - items by other authors that mention our reply text
 *
 * It never types, never clicks a submit control, and never posts. Read-only by
 * construction. The ego-browser runtime does not inherit shell environment
 * variables, so parameters are read from a JSON file:
 *
 *   {"task": 2, "url": "https://...", "own": "Polyv的小幕", "page": "p1"}
 *
 * Default path: /tmp/polyv_reply_check_params.json
 */

const fs = await import("node:fs/promises");
let params = {};
try {
  params = JSON.parse(await fs.readFile("/tmp/polyv_reply_check_params.json", "utf8"));
} catch {
  params = {};
}
const taskSpaceId = Number(params.task || 0);
const targetUrl = params.url || "";
const ownAccount = params.own || "";
const pageLabel = params.page || "p1";
const maxScrollRounds = Number(params.maxRounds || 8);

const result = { url: targetUrl, ok: false, own: [], othersMentioningOwnText: [], itemCount: 0, rounds: 0 };

try {
  if (!taskSpaceId || !targetUrl || !ownAccount) {
    throw new Error("params file needs task, url and own");
  }
  const task = await taskSpace(taskSpaceId);
  const page = task.page(pageLabel);
  await page.goto(targetUrl);
  await page.waitForTimeout(6500);

  const clickExpands = () => {
    let clicked = 0;
    for (const el of document.querySelectorAll("span,div,button,a")) {
      const text = (el.textContent || "").trim();
      if (el.children.length === 0 && /^展开/.test(text) && text.length < 16) {
        el.click();
        clicked += 1;
      }
    }
    return clicked;
  };

  const extract = (own) => {
    const items = [...document.querySelectorAll('[data-e2e="comment-item"]')];
    const rows = items.map((item) => {
      const author = (item.querySelector('[data-e2e="comment-user-name"]')?.innerText || "").trim();
      const text = (item.innerText || "").replace(/\s+/g, " ").trim();
      const expand = [...item.querySelectorAll("span,div,button,a")]
        .filter((el) => el.children.length === 0 && /^展开/.test((el.textContent || "").trim()))
        .map((el) => (el.textContent || "").trim());
      return { author, text: text.slice(0, 160), expand: [...new Set(expand)] };
    });
    return {
      itemCount: rows.length,
      own: rows.filter((row) => row.author === own).map((row) => ({ text: row.text.slice(0, 130), expand: row.expand })),
      others: rows,
    };
  };

  await page.evaluate(clickExpands);
  await page.waitForTimeout(1500);
  let data = await page.evaluate(extract, ownAccount);
  while (data.own.length === 0 && result.rounds < maxScrollRounds) {
    result.rounds += 1;
    await page.evaluate(() => {
      const list = document.querySelector('[data-e2e="comment-list"]');
      let node = list;
      for (let index = 0; index < 8 && node; index += 1) {
        if (node.scrollHeight > node.clientHeight + 30) node.scrollTop = node.scrollHeight;
        node = node.parentElement;
      }
      window.scrollTo(0, document.body.scrollHeight);
    });
    await page.waitForTimeout(1200);
    await page.evaluate(clickExpands);
    await page.waitForTimeout(1200);
    const next = await page.evaluate(extract, ownAccount);
    if (next.itemCount === data.itemCount && next.own.length === 0) break;
    data = next;
  }

  result.ok = true;
  result.itemCount = data.itemCount;
  result.own = data.own;
  result.othersMentioningOwnText = data.others
    .filter((row) => row.author !== ownAccount && /想问问具体咋样|我也遇到了一样的问题|后来顺利吗/.test(row.text))
    .map((row) => ({ author: row.author, text: row.text.slice(0, 130) }));
} catch (error) {
  result.error = String(error?.message || error).slice(0, 200);
}

console.log("REPLYCHECK " + JSON.stringify(result));

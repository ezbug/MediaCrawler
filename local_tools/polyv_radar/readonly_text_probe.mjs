/**
 * Read-only text probe: open a URL and print the rendered text around a
 * needle. Params from /tmp/polyv_text_probe_params.json:
 *   {"task": 2, "url": "https://...", "needle": "关键词", "page": "p1"}
 */

const fs = await import("node:fs/promises");
let params = {};
try {
  params = JSON.parse(await fs.readFile("/tmp/polyv_text_probe_params.json", "utf8"));
} catch {
  params = {};
}

const result = { url: params.url || "", needle: params.needle || "", found: false, snippet: "" };

try {
  const task = await taskSpace(Number(params.task || 0));
  const page = task.page(params.page || "p1");
  await page.goto(result.url);
  await page.waitForTimeout(6500);
  await page.evaluate(() => {
    for (const el of document.querySelectorAll("div,span,button,a")) {
      const text = (el.textContent || "").trim();
      if (el.children.length === 0 && text.length < 20 && /展开|条评论/.test(text)) {
        el.click();
      }
    }
    window.scrollTo(0, document.body.scrollHeight);
  });
  await page.waitForTimeout(2500);
  const probe = await page.evaluate((needle) => {
    const body = (document.body.innerText || "").replace(/\s+/g, " ");
    const index = body.indexOf(needle);
    return index >= 0 ? body.slice(Math.max(0, index - 220), index + 340) : "";
  }, result.needle);
  result.found = Boolean(probe);
  result.snippet = probe;
} catch (error) {
  result.error = String((error && error.message) || error).slice(0, 160);
}

console.log("PROBE " + JSON.stringify(result).slice(0, 2200));

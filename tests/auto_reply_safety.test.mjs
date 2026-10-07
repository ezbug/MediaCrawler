import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import {
  parseArgs,
  isDuplicateReply,
  isDuplicateTarget,
  targetIdentity,
  postedTextOutsideEditor,
  classifyFailure,
  ensureWindowRestored,
  assertReplyRateLimit,
  matchesZhihuTarget,
  verifyXhsPostedText,
  verifiedSubmission,
  inspectPostedDom,
  openReplyPage,
  assertBiliVideoTarget,
  installBiliPlaybackGuardDom,
  clickBiliReplyDom,
  clickUniqueXhsReplyTarget,
  clickUniqueBiliReplyTarget,
  expandUniqueXhsRepliesDom,
} from "/Users/sexpistole111/.codex/skills/polyv-lead-auto-reply/scripts/auto_reply.mjs";

test('XHS recheck expands only uniquely matched target replies', () => {
  const previous = globalThis.document;
  let clicked = 0;
  const item = quote => ({querySelector(selector) {
    return {innerText: selector === '.content' ? quote : '同名'};
  }, closest: () => ({querySelector: () => ({click(){clicked++;}})})});
  try {
    globalThis.document = {querySelectorAll: () => [item('其他原话'),item('完整需求')]};
    assert.equal(expandUniqueXhsRepliesDom({targetAuthor:'同名',targetQuote:'完整需求'}),true);
    assert.equal(clicked,1);
    globalThis.document = {querySelectorAll: () => [item('完整需求'),item('完整需求')]};
    assert.equal(expandUniqueXhsRepliesDom({targetAuthor:'同名',targetQuote:'完整需求'}),false);
    assert.equal(expandUniqueXhsRepliesDom({targetAuthor:'同名',targetQuote:''}),false);
    assert.equal(clicked,1);
  } finally {globalThis.document=previous;}
});

test('XHS comment recheck expands multiple pages without another submission', async () => {
  let expansions = 0;
  let reloads = 0;
  const page = {evaluate: async fn => {
    if(fn === expandUniqueXhsRepliesDom){expansions++;return true;}
    return {posted_text:expansions >= 3,own_account:true,target_relation:true};
  }, waitForTimeout:async()=>{},reload:async()=>{reloads++;}};
  assert.equal(await verifyXhsPostedText(page,'完整回复','作者','原话','comment','id:ours'),true);
  assert.equal(expansions,3);
  assert.equal(reloads,0);
});

test('Bili same-name users require exactly one full-quote match', () => {
  const previous = globalThis.document;
  let clicked = 0;
  const thread = text => ({shadowRoot:{querySelector:()=>({shadowRoot:{querySelector:selector => {
    if(selector==='bili-comment-user-info')return {shadowRoot:{querySelector:()=>({innerText:'同名'})}};
    if(selector==='bili-rich-text')return {shadowRoot:{querySelector:()=>({innerText:text})}};
    return {shadowRoot:{querySelector:()=>({click(){clicked++;}})}};
  }}})}});
  try {
    let threads = [thread('别人的原话'),thread('我的完整需求')];
    globalThis.document={querySelector:()=>({shadowRoot:{querySelectorAll:()=>threads}})};
    assert.equal(clickUniqueBiliReplyTarget({targetAuthor:'同名',targetQuote:'我的完整需求'}),true);
    assert.equal(clicked,1);
    assert.equal(clickUniqueBiliReplyTarget({targetAuthor:'同名',targetQuote:''}),false);
    threads=[thread('我的完整需求'),thread('我的完整需求')];
    assert.equal(clickUniqueBiliReplyTarget({targetAuthor:'同名',targetQuote:'我的完整需求'}),false);
    assert.equal(clicked,1);
  } finally {globalThis.document=previous;}
});

test('XHS same-name users require a unique matching quote', () => {
  const previous = globalThis.document;
  let clicked = 0;
  const item = text => ({querySelector(selector) {
    if (selector.includes('.author')) return {innerText:'momo'};
    if (selector === '.content') return {innerText:text};
    return {click(){clicked++;}};
  }});
  try {
    globalThis.document = {querySelectorAll:() => [item('another quote'),item('my clients do not reply')]};
    assert.equal(clickUniqueXhsReplyTarget({targetAuthor:'momo',targetQuote:'my clients do not reply'}),true);
    assert.equal(clicked,1);
    globalThis.document = {querySelectorAll:() => [item('same'),item('same')]};
    assert.equal(clickUniqueXhsReplyTarget({targetAuthor:'momo',targetQuote:'same'}),false);
    assert.equal(clicked,1);
  } finally { globalThis.document = previous; }
});

test('XHS committed navigation timeout requires actual expected page proof', async () => {
  const error = Object.assign(new Error('timeout'), {name:'PageNavigationTimeoutError'});
  await openReplyPage({goto:async()=>{throw error;},evaluate:async()=>true},'xhs','https://www.xiaohongshu.com/explore/note');
  await assert.rejects(openReplyPage({goto:async()=>{throw error;},evaluate:async()=>false},'xhs','https://www.xiaohongshu.com/explore/note'), /timeout/);
});

test('Bili committed timeout requires canonical, native video and comments proof', async () => {
  const saved = {document:globalThis.document, location:globalThis.location, window:globalThis.window};
  const url = 'https://www.bilibili.com/video/BV1rGaV6WEwf/';
  const error = Object.assign(new Error('timeout'), {name:'PageNavigationTimeoutError'});
  globalThis.location = {href:url};
  globalThis.window = {__INITIAL_STATE__:{bvid:'BV1rGaV6WEwf'}};
  globalThis.document = {body:{innerText:'评论'}, querySelector:selector=>selector.includes('canonical')?{getAttribute:()=>url}: {}, querySelectorAll:()=>[], addEventListener:()=>{}};
  const page = {goto:async()=>{throw error;},evaluate:async(fn,arg)=>fn(arg)};
  try {
    await openReplyPage(page,'bili',url);
    globalThis.window.__INITIAL_STATE__.bvid='BVwrong';
    await assert.rejects(openReplyPage(page,'bili',url), /timeout/);
    globalThis.window.__INITIAL_STATE__.bvid='BV1rGaV6WEwf';
    globalThis.document.body.innerText='安全验证';
    await assert.rejects(openReplyPage(page,'bili',url), /timeout/);
  } finally {Object.assign(globalThis,saved);}
});

test("XHS delayed comment is checked before refreshing", async () => {
  let calls = 0;
  let reloads = 0;
  const page = {
    evaluate: async () => ({ posted_text: ++calls === 25, own_account: true, target_relation: true }),
    waitForTimeout: async () => {},
    reload: async () => { reloads += 1; },
  };
  assert.equal(await verifyXhsPostedText(page, "回复", "作者", "原话", "post", "我方账号"), true);
  assert.equal(reloads, 0);
});

test("CLI defaults to dry-run and parses target fields", () => {
  const args = parseArgs([
    "--platform", "dy",
    "--url", "https://www.douyin.com/video/1",
    "--author", "用户",
    "--text", "测试回复",
    "--taskspace", "8",
  ]);

  assert.equal(args.platform, "dy");
  assert.equal(args.submit, false);
  assert.equal(args.author, "用户");
  assert.equal(args.taskspace, 8);
});

test("CLI preserves post-level source type for separate locator flow", () => {
  const args = parseArgs([
    "--platform", "xhs",
    "--url", "https://www.xiaohongshu.com/explore/1",
    "--source-type", "post",
    "--author", "作者",
    "--quote", "活动报价",
    "--text", "测试回复",
    "--taskspace", "8",
  ]);

  assert.equal(args.sourceType, "post");
});

test("知乎目标匹配同时要求作者和原文", () => {
  assert.equal(matchesZhihuTarget("作者 起风了\n中小企业培训数字化选型", {
    author: "起风了",
    quote: "中小企业培训数字化选型",
  }), true);
  assert.equal(matchesZhihuTarget("作者 起风了\n另一篇文章", {
    author: "起风了",
    quote: "中小企业培训数字化选型",
  }), false);
});

test("知乎回复脚本会先定位目标回答再打开评论框", async () => {
  const source = await readFile(
    "/Users/sexpistole111/.codex/skills/polyv-lead-auto-reply/scripts/auto_reply.mjs",
    "utf8",
  );
  assert.match(source, /ContentItem\.AnswerItem/);
  assert.match(source, /article\.Post-Main/);
  assert.match(source, /AuthorInfo/);
  assert.match(source, /添加评论/);
  assert.match(source, /data-zop/);
});

test("知乎真实发送会命中发布按钮并轮询验证", async () => {
  const source = await readFile(
    "/Users/sexpistole111/.codex/skills/polyv-lead-auto-reply/scripts/auto_reply.mjs",
    "utf8",
  );
  assert.match(source, /innerText\?\.trim\(\) === '发布'/);
  assert.match(source, /attempt < 8 && !verified/);
  assert.match(source, /if \(prepared\) await page\.keyboard\.insertText\(text\)/);
});

test("post-level targets do not reuse comment-author matching", async () => {
  const source = await readFile(
    "/Users/sexpistole111/.codex/skills/polyv-lead-auto-reply/scripts/auto_reply.mjs",
    "utf8",
  );
  assert.match(source, /const contentLevel = \['post', 'answer', 'content'\]/);
  assert.match(source, /author && !contentLevel/);
  assert.match(source, /verifyXhsPostedText\(page, text, author, quote, sourceType, ownAccount, url\)/);
});

test("CLI requires an explicit Ego Lite TaskSpace", () => {
  assert.throws(() => parseArgs([
    "--platform", "dy",
    "--url", "https://www.douyin.com/video/1",
    "--text", "测试回复",
  ]), /taskspace/);
});

test("auto-reply reuses the provided TaskSpace without takeover", async () => {
  const source = await readFile(
    "/Users/sexpistole111/.codex/skills/polyv-lead-auto-reply/scripts/auto_reply.mjs",
    "utf8",
  );
  assert.match(source, /taskSpace\(taskspace\)/);
  assert.doesNotMatch(source, /takeOverTaskSpace/);
});

test("duplicate replies are rejected by target and text key", () => {
  const history = [{
    platform: "dy",
    target_url: "https://www.douyin.com/video/1",
    target_author: "用户",
    reply_text: "测试回复",
    mode: "live",
    submitted: true,
  }];

  assert.equal(isDuplicateReply(history, {
    platform: "dy",
    url: "https://www.douyin.com/video/1",
    author: "用户",
    text: "测试回复",
  }), true);
});

test("Dry-Run记录不会阻止后续真实发送", () => {
  const history = [{
    platform: "zhihu",
    target_url: "https://www.zhihu.com/question/1/answer/2",
    target_author: "用户",
    reply_text: "测试回复",
    mode: "dry_run",
    submitted: false,
  }];

  assert.equal(isDuplicateReply(history, {
    platform: "zhihu",
    url: "https://www.zhihu.com/question/1/answer/2",
    author: "用户",
    text: "测试回复",
  }), false);
});

test("rate limit enforces cooldown while allowing an explicit optional cap", () => {
  const now = new Date("2026-09-14T12:00:00.000Z");
  const recent = [{ timestamp: "2026-09-14T11:59:45.000Z", platform: "dy", mode: "live", submitted: true }];
  assert.throws(() => assertReplyRateLimit(recent, "dy", now), /30秒/);

  const daily = Array.from({ length: 5 }, (_, index) => ({
    timestamp: `2026-09-14T0${index}:00:00.000Z`,
    platform: "dy",
    mode: "live",
    submitted: true,
  }));
  assert.doesNotThrow(() => assertReplyRateLimit(daily, "dy", now));
  assert.throws(() => assertReplyRateLimit(daily, "dy", now, { dailyLimit: 5 }), /每日最多5条/);
});

// --- Hermes takeover fixes: dedupe identity, click/verify split, editor text ---

test("改文案不能绕过去重：同一目标换稿仍然判重", () => {
  const history = [{
    platform: "zhihu",
    target_url: "https://zhuanlan.zhihu.com/p/1",
    target_author: "lumina",
    target_quote: "有没有防录屏的视频分享平台？",
    reply_text: "第一版文案",
    mode: "live",
    submitted: true,
    clicked: true,
    verified: true,
  }];

  // same target, completely different wording
  assert.equal(isDuplicateTarget(history, {
    platform: "zhihu",
    url: "https://zhuanlan.zhihu.com/p/1",
    author: "lumina",
    quote: "有没有防录屏的视频分享平台？",
  }), true);

  // the old text-based key would NOT have caught this
  assert.equal(isDuplicateReply(history, {
    platform: "zhihu",
    url: "https://zhuanlan.zhihu.com/p/1",
    author: "lumina",
    text: "第二版换了个说法的文案",
  }), false);
});

test("同一页面不同评论目标不算重复", () => {
  const history = [{
    platform: "zhihu",
    target_url: "https://zhuanlan.zhihu.com/p/1989299790115275469",
    target_author: "lumina",
    target_quote: "同学，这种‘切屏录制’的情况确实防不胜防。",
    reply_text: "回复回答",
    mode: "live",
    submitted: true,
  }];

  assert.equal(isDuplicateTarget(history, {
    platform: "zhihu",
    url: "https://zhuanlan.zhihu.com/p/1989299790115275469",
    author: "lumina",
    quote: "有没有防录屏的视频分享平台？",
  }), false);
});

test("点击后未核验也不会重发（结果不明只回查）", () => {
  const history = [{
    platform: "zhihu",
    target_url: "https://zhuanlan.zhihu.com/p/2041988765355331922",
    target_author: "Video TV",
    target_quote: "直播平台怎么选",
    reply_text: "已点击但回查失败",
    mode: "live",
    clicked: true,
    submitted: true,
    verified: false,
    status: "submitted_unverified",
  }];

  assert.equal(isDuplicateTarget(history, {
    platform: "zhihu",
    url: "https://zhuanlan.zhihu.com/p/2041988765355331922",
    author: "Video TV",
    quote: "直播平台怎么选",
  }), true);
});

test("编辑器里的文本不算已发布", () => {
  const reply = "企业内训建议把SOP拆成微课";
  // text still sitting in the composer only
  assert.equal(postedTextOutsideEditor(`草稿区 ${reply}`, reply, reply), false);
  // text rendered in the page body and the editor is empty
  assert.equal(postedTextOutsideEditor(`评论区 ${reply}`, "", reply), true);
  // text present in AND out of the editor must still count as a draft
  assert.equal(postedTextOutsideEditor(`评论区 ${reply}`, `编辑器 ${reply}`, reply), false);
  // empty needle is never a match
  assert.equal(postedTextOutsideEditor("anything", "", ""), false);
});

test("草稿记录不阻止后续真实发送（dry_run 仍可发）", () => {
  const history = [{
    platform: "zhihu",
    target_url: "https://zhuanlan.zhihu.com/p/1",
    target_author: "lumina",
    target_quote: "报价多少",
    reply_text: "dry run 文案",
    mode: "dry_run",
    clicked: false,
    submitted: false,
    verified: false,
  }];

  assert.equal(isDuplicateTarget(history, {
    platform: "zhihu",
    url: "https://zhuanlan.zhihu.com/p/1",
    author: "lumina",
    quote: "报价多少",
  }), false);
});

test("targetIdentity 忽略回复文案但保留原话", () => {
  const base = { platform: "dy", url: "https://www.douyin.com/video/1", author: "用户", quote: "预算多少" };
  assert.equal(
    targetIdentity(base),
    targetIdentity({ ...base }),
  );
  assert.notEqual(
    targetIdentity(base),
    targetIdentity({ ...base, quote: "另一个问题" }),
  );
});

test("失败分类覆盖落账所需的全部失败码", () => {
  assert.equal(classifyFailure("无法定位dy回复输入框"), "input_unavailable");
  assert.equal(classifyFailure("检测到同一目标已触达，已阻止重复回评（去重不依赖文案）"), "duplicate_blocked");
  assert.equal(classifyFailure("点击发送后未验证到相同评论文本，已记录为未确认发送"), "clicked_unverified");
});

// --- screenshot pipeline: minimized window kills Page.captureScreenshot ---

function stubPage(windowInfo, { fail = false } = {}) {
  const calls = [];
  return {
    calls,
    async cdp(method, params) {
      calls.push({ method, params });
      if (fail) throw new Error("No web contents in the target");
      if (method === "Browser.getWindowForTarget") return windowInfo;
      return {};
    },
    async waitForTimeout(ms) {
      calls.push({ method: "waitForTimeout", params: { ms } });
    },
  };
}

test("最小化窗口会被先恢复再截图", async () => {
  const page = stubPage({ windowId: 42, bounds: { windowState: "minimized" } });
  const restored = await ensureWindowRestored(page);

  assert.equal(restored, true);
  const set = page.calls.find((c) => c.method === "Browser.setWindowBounds");
  assert.deepEqual(set.params, { windowId: 42, bounds: { windowState: "normal" } });
  // a settle wait is applied because the window really was minimized
  assert.ok(page.calls.some((c) => c.method === "waitForTimeout"));
});

test("未最小化的窗口不做多余等待但仍确保 normal", async () => {
  const page = stubPage({ windowId: 7, bounds: { windowState: "normal" } });
  const restored = await ensureWindowRestored(page);

  assert.equal(restored, true);
  assert.deepEqual(page.calls.find((c) => c.method === "Browser.setWindowBounds").params, {
    windowId: 7,
    bounds: { windowState: "normal" },
  });
  assert.equal(page.calls.some((c) => c.method === "waitForTimeout"), false);
});

test("恢复失败不抛错，返回 false（降级到 DOM 证据）", async () => {
  const page = stubPage(null, { fail: true });
  assert.equal(await ensureWindowRestored(page), false);
});

test("拿不到 windowId 时返回 null", async () => {
  const page = stubPage({ bounds: { windowState: "normal" } });
  assert.equal(await ensureWindowRestored(page), null);
});

test("截图前必然先调用 ensureWindowRestored", async () => {
  const { readFile } = await import("node:fs/promises");
  const source = await readFile(
    "/Users/sexpistole111/.codex/skills/polyv-lead-auto-reply/scripts/auto_reply.mjs",
    "utf8",
  );
  assert.match(source, /state\.windowRestored = await ensureWindowRestored\(page\)/);
  assert.match(source, /Browser\.setWindowBounds/);
});

test("verified submission requires three positive booleans", () => {
  const complete = { posted_text: true, own_account: true, target_relation: true };
  assert.equal(verifiedSubmission(complete), true);
  assert.equal(verifiedSubmission(null), false);
  for (const field of Object.keys(complete)) {
    for (const value of [null, false, undefined, "true", 1]) {
      assert.equal(verifiedSubmission({ ...complete, [field]: value }), false);
    }
  }
});

test("submit requires own account before opening any browser", () => {
  const args = ["--url", "https://example.com/1", "--text", "reply", "--taskspace", "8", "--submit"];
  assert.throws(() => parseArgs(args), /--own-account/);
  assert.throws(() => parseArgs([...args, "--own-account", "  "]), /--own-account/);
  assert.equal(parseArgs([...args, "--own-account", "id:123"]).ownAccount, "id:123");
});

// Minimal DOM fixture for the selectors used by the production inspector.
class FixtureNode {
  constructor(tag = "div", classes = "", text = "", attrs = {}, children = []) {
    this.tag = tag;
    this.classes = classes.split(" ");
    this.ownText = text;
    this.attrs = attrs;
    this.children = children;
    for (const child of children) child.parentElement = this;
  }
  get textContent() { return this.ownText + this.children.map((child) => child.textContent).join("\n"); }
  get innerText() { return this.textContent; }
  getAttribute(key) { return this.attrs[key] ?? null; }
  getRootNode() { return this.parentElement ? this.parentElement.getRootNode() : this; }
  matches(selector) {
    return selector.split(",").some((part) => {
      const tokens = part.trim().split(/\s+/);
      const simple = tokens.pop();
      const element = simple.replace(/\[[^\]]*\]/g, "");
      const tag = element.match(/^[a-z][\w-]*/)?.[0];
      if (tag && tag !== this.tag) return false;
      if ([...element.matchAll(/\.([\w-]+)/g)].some((m) => !this.classes.includes(m[1]))) return false;
      const id = element.match(/#([\w-]+)/)?.[1];
      if (id && this.attrs.id !== id) return false;
      for (const m of simple.matchAll(/\[([\w-]+)(?:(\*?=)"([^\"]*)")?\]/g)) {
        const value = this.getAttribute(m[1]);
        if (value === null || (m[2] === "=" && value !== m[3]) || (m[2] === "*=" && !value.includes(m[3]))) return false;
      }
      if (!tokens.length) return true;
      for (let ancestor = this.parentElement; ancestor; ancestor = ancestor.parentElement) {
        if (ancestor.matches(tokens.join(" "))) return true;
      }
      return false;
    });
  }
  querySelectorAll(selector) {
    return this.children.flatMap((child) => [ ...(child.matches(selector) ? [child] : []), ...child.querySelectorAll(selector)]);
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
}

const node = (...args) => new FixtureNode(...args);
function comment(name, text, { id = "", children = [], tag = "div", classes = "comment-item" } = {}) {
  return node(tag, classes, "", {}, [
    node("div", "author-wrapper", "", {}, [node("a", "name", name, { href: `/user/profile/${id || "other"}` })]),
    node("div", "content", text),
    ...children,
  ]);
}
const inspectionArgs = { replyText: "Full reply", targetAuthor: "Target", targetQuote: "Original question", ownName: "Our account", contentLevelTarget: false };
function inspectFixture(children, args = {}, location = "https://www.xiaohongshu.com/explore/1") {
  const previous = globalThis.document;
  const document = node("document", "", "", {}, children);
  document.location = new URL(location);
  globalThis.document = document;
  try { return inspectPostedDom({ ...inspectionArgs, ...args }); }
  finally { if (previous === undefined) delete globalThis.document; else globalThis.document = previous; }
}

test("XHS reply belongs to exact author and closest target parent", () => {
  const ours = comment("Our account", "Full reply");
  const parent = node("div", "parent-comment", "", {}, [
    comment("Target", "Original question"), node("div", "reply-container", "", {}, [ours]),
  ]);
  assert.equal(verifiedSubmission(inspectFixture([parent])), true);
  assert.equal(verifiedSubmission(inspectFixture([parent], { ownName: "Our" })), false);
  assert.equal(verifiedSubmission(inspectFixture([parent], { ownName: "id:other" })), true);
  assert.equal(verifiedSubmission(inspectFixture([parent], { ownName: "other" })), true);
  assert.equal(verifiedSubmission(inspectFixture([parent], { ownName: "id:wrong" })), false);
  assert.equal(inspectFixture([parent], { ownName: "" }).own_account, null);
});

test("body, article fragments and editor drafts cannot prove XHS publication", () => {
  const article = node("article", "note-detail", "Our account Full reply Target Original question");
  const editor = node("div", "", "", { contenteditable: "true" }, [comment("Our account", "Full reply")]);
  for (const children of [[article], [editor], [node("div", "", "Full reply")]]) {
    const evidence = inspectFixture(children, { contentLevelTarget: true });
    assert.equal(evidence.posted_text, false);
    assert.equal(evidence.own_account, false);
    assert.equal(verifiedSubmission(evidence), false);
  }
});

test("exact full reply and account must be in the same comment", () => {
  for (const [name, text] of [["Other account", "Full reply"], ["Our account extra", "Full reply"], ["Our account", "Full reply extra"], ["Our account", "Full"]]) {
    const result = inspectFixture([comment("Target", "Original question", { children: [comment(name, text)] })]);
    assert.equal(verifiedSubmission(result), false);
  }
  const mixed = comment("Target", "Original question", { children: [comment("Other account", "Full reply"), comment("Our account", "different reply")] });
  assert.equal(verifiedSubmission(inspectFixture([mixed])), false);
});

test("unrelated body or duplicate text on another target cannot supply relation", () => {
  const wrong = comment("Different target", "Original question", { children: [comment("Our account", "Full reply")] });
  const correct = comment("Target", "Original question");
  assert.equal(verifiedSubmission(inspectFixture([wrong, correct, node("div", "", "Target Original question Our account")])), false);
  assert.equal(verifiedSubmission(inspectFixture([comment("Target extra", "Original question", { children: [comment("Our account", "Full reply")] })])), false);
  const both = comment("Target", "Original question", { children: [comment("Our account", "Full reply")] });
  assert.equal(verifiedSubmission(inspectFixture([wrong, both])), true);
});

test("post-level XHS requires independently matched article identity and quote", () => {
  const article = node("article", "note-detail", "", {}, [
    node("div", "author-container", "", {}, [node("a", "username", "Target")]),
    node("div", "desc", "Original question"),
  ]);
  const reply = comment("Our account", "Full reply");
  const args = { contentLevelTarget: true, targetUrl: "https://www.xiaohongshu.com/explore/1" };
  assert.equal(verifiedSubmission(inspectFixture([article, reply], args)), true);
  assert.equal(verifiedSubmission(inspectFixture([article, reply], { ...args, targetAuthor: "Other" })), false);
  assert.equal(verifiedSubmission(inspectFixture([article, reply], { ...args, targetUrl: "https://www.xiaohongshu.com/explore/2" })), false);
  assert.equal(verifiedSubmission(inspectFixture([reply], args)), false);
});

test("Bili shadow DOM proves own reply and root-thread relation", () => {
  function shadowComment(tag, name, text, id) {
    const user = node("bili-comment-user-info");
    user.shadowRoot = node("shadow-root", "", "", {}, [node("a", "", name, { href: `https://space.bilibili.com/${id}` })]);
    user.shadowRoot.host = user;
    const richText = node("bili-rich-text");
    richText.shadowRoot = node("shadow-root", "", "", {}, [node("div", "", text, { id: "contents" })]);
    richText.shadowRoot.host = richText;
    const renderer = node(tag);
    renderer.shadowRoot = node("shadow-root", "", "", {}, [user, richText]);
    renderer.shadowRoot.host = renderer;
    return renderer;
  }
  const ours = shadowComment("bili-comment-reply-renderer", "Our account", "Full reply", "123");
  const original = shadowComment("bili-comment-renderer", "Target", "Original question", "456");
  const thread = node("bili-comment-thread-renderer");
  thread.shadowRoot = node("shadow-root", "", "", {}, [original, ours]);
  thread.shadowRoot.host = thread;
  const comments = node("bili-comments");
  comments.shadowRoot = node("shadow-root", "", "", {}, [thread]);
  comments.shadowRoot.host = comments;
  assert.equal(verifiedSubmission(inspectFixture([comments])), true);
  assert.equal(verifiedSubmission(inspectFixture([comments], { ownName: "id:123" })), true);
  assert.equal(verifiedSubmission(inspectFixture([comments], { ownName: "Other" })), false);
});

test("XHS verifier never accepts unknown account and waits 30 seconds before reload", async () => {
  const events = [];
  const page = {
    evaluate: async () => ({ posted_text: true, own_account: null, target_relation: true }),
    waitForTimeout: async (ms) => events.push(ms),
    reload: async () => events.push("reload"),
    waitForLoadState: async () => {},
  };
  assert.equal(await verifyXhsPostedText(page, "reply", "target", "", "post"), false);
  assert.equal(events.slice(0, events.indexOf("reload")).reduce((sum, ms) => sum + ms, 0), 30000);
  assert.equal(events.filter((event) => event === "reload").length, 1);
});

const biliVideoUrl = "https://www.bilibili.com/video/BV13Pt46YEXW/";
const biliPostArgs = {
  currentPlatform: "bili", contentLevelTarget: true, targetUrl: biliVideoUrl,
  targetAuthor: "企顾司", targetQuote: "企业培训视频", ownName: "id:350237651",
};
function biliPostFixture({ canonical = biliVideoUrl, title = "企业培训视频", author = "企顾司", authorId = "1838952296", ownId = "350237651", replyText = "Full reply", recommendationOnly = false } = {}) {
  const upInfo = node("div", "up-info-container", "", {}, [
    node("div", "up-info--right", "官网www.cegos.com.cn", {}, [
      node("a", "", author, { href: `https://space.bilibili.com/${authorId}/?spm_id_from=333.788.upinfo.detail.click` }),
    ]),
  ]);
  const upPanel = node("div", "up-panel-container", "", {}, [upInfo]);
  const ownComment = node("bili-comment-renderer");
  ownComment.shadowRoot = node("shadow-root", "", "", {}, [
    node("a", "", "Our account", { href: `https://space.bilibili.com/${ownId}/` }),
    node("div", "", replyText, { id: "contents" }),
  ]);
  ownComment.shadowRoot.host = ownComment;
  return [
    ...(canonical === null ? [] : [node("link", "", "", { rel: "canonical", href: canonical })]),
    node("div", "video-info-container", "", {}, [node("h1", "video-title special-text-indent", title)]),
    recommendationOnly ? node("div", "video-page-card-small", "", {}, [upPanel, node("a", "upname", author)]) : upPanel,
    ownComment,
  ];
}

test("Bili post matches canonical video, separate main title and sidebar UP by exact name or ID", () => {
  for (const targetAuthor of ["企顾司", "id:1838952296", "1838952296"]) {
    const evidence = inspectFixture(biliPostFixture(), { ...biliPostArgs, targetAuthor }, biliVideoUrl + "?spm_id_from=333.788");
    assert.equal(verifiedSubmission(evidence), true);
  }
  assert.equal(verifiedSubmission(inspectFixture(biliPostFixture({ canonical: biliVideoUrl.slice(0, -1) }), biliPostArgs, biliVideoUrl)), true);
  assert.equal(verifiedSubmission(inspectFixture(biliPostFixture(), {
    ...biliPostArgs, targetUrl: biliVideoUrl.slice(0, -1) + "?spm_id_from=333.788",
  }, biliVideoUrl + "?autoplay=0")), true);
});

test("Bili post rejects matching recommended UP and partial main author names", () => {
  for (const fixture of [biliPostFixture({ recommendationOnly: true }), biliPostFixture({ author: "企顾司其他账号" })]) {
    const evidence = inspectFixture(fixture, biliPostArgs, biliVideoUrl);
    assert.equal(evidence.posted_text, true);
    assert.equal(evidence.own_account, true);
    assert.equal(evidence.target_relation, false);
  }
  const wrongMain = biliPostFixture({ author: "Other UP", authorId: "123" });
  wrongMain.push(node("div", "video-page-card-small", "", {}, [node("a", "upname", "企顾司", { href: "https://space.bilibili.com/1838952296/" })]));
  assert.equal(verifiedSubmission(inspectFixture(wrongMain, biliPostArgs, biliVideoUrl)), false);
  assert.equal(verifiedSubmission(inspectFixture(biliPostFixture({ authorId: "123" }), { ...biliPostArgs, targetAuthor: "id:1838952296" }, biliVideoUrl)), false);
});

test("Bili post rejects missing/wrong canonical, page video, title, own ID and partial reply", () => {
  const cases = [
    { canonical: null },
    { canonical: "https://www.bilibili.com/video/BVother/" },
    { canonical: "https://example.test/video/BV13Pt46YEXW/" },
    { title: "Unrelated title" },
    { ownId: "123" },
    { replyText: "Full reply extra" },
    { replyText: "Full" },
  ];
  for (const options of cases) {
    assert.equal(verifiedSubmission(inspectFixture(biliPostFixture(options), biliPostArgs, biliVideoUrl)), false);
  }
  assert.equal(verifiedSubmission(inspectFixture(biliPostFixture(), biliPostArgs, "https://www.bilibili.com/video/BVother/")), false);
  assert.equal(verifiedSubmission(inspectFixture(biliPostFixture(), { ...biliPostArgs, targetUrl: "" }, biliVideoUrl)), false);
});

test("Bili navigation pauses videos immediately after goto", async () => {
  const events = [];
  const previous = globalThis.document;
  globalThis.document = {
    querySelectorAll: () => [{ pause: () => events.push("pause") }],
    addEventListener: (type, listener, capture) => events.push([type, capture]),
  };
  const page = {
    goto: async (url) => events.push(["goto", url]),
    evaluate: async (fn) => { events.push("evaluate"); return fn(); },
  };
  try {
    await openReplyPage(page, "bili", biliVideoUrl);
    assert.deepEqual(events, [["goto", biliVideoUrl], "evaluate", ["play", true], "pause"]);
    events.length = 0;
    await openReplyPage(page, "xhs", "https://www.xiaohongshu.com/explore/1");
    assert.deepEqual(events, [["goto", "https://www.xiaohongshu.com/explore/1"]]);
  } finally { if (previous === undefined) delete globalThis.document; else globalThis.document = previous; }
});

test("Bili pre-submit guard rejects autoplay to another video even with unchanged canonical", async () => {
  const oldVideo = "https://www.bilibili.com/video/BV2022Old/";
  for (const [currentUrl, canonicalUrl] of [[oldVideo, oldVideo], [oldVideo, biliVideoUrl], [biliVideoUrl, oldVideo], [biliVideoUrl, ""]]) {
    let clicked = false;
    const page = { evaluate: async () => ({ currentUrl, canonicalUrl }) };
    await assert.rejects(async () => {
      await assertBiliVideoTarget(page, biliVideoUrl);
      clicked = true;
    }, /视频目标已变化|canonical/);
    assert.equal(clicked, false);
  }
  assert.equal(await assertBiliVideoTarget({ evaluate: async () => ({ currentUrl: biliVideoUrl + "?p=1", canonicalUrl: biliVideoUrl.slice(0, -1) }) }, biliVideoUrl), true);
  assert.equal(await assertBiliVideoTarget({ evaluate: async () => ({
    currentUrl: biliVideoUrl + "?autoplay=0", canonicalUrl: biliVideoUrl,
  }) }, biliVideoUrl.slice(0, -1) + "?spm_id_from=333.788"), true);
});

test("Bili runtime checks video target before preparation and again immediately before submit", async () => {
  const source = await readFile("/Users/sexpistole111/.codex/skills/polyv-lead-auto-reply/scripts/auto_reply.mjs", "utf8");
  assert.match(source, /assertBiliVideoTarget\(page, url\);\s*\n\s*let prepared/);
  assert.match(source, /if \(submit\) \{\s*if \(platform === 'bili'\) await assertBiliVideoTarget\(page, url\);\s*clicked = platform === 'bili' \? await page\.evaluate\(clickBiliReplyDom, url\)/);
});

test("Bili page capture listener pauses new/resumed videos and installs only once", () => {
  const previous = globalThis.document;
  const listeners = [];
  let existingPaused = 0;
  let newPaused = 0;
  globalThis.document = {
    addEventListener: (...args) => listeners.push(args),
    querySelectorAll: () => [{ pause: () => { existingPaused += 1; } }],
  };
  try {
    installBiliPlaybackGuardDom();
    installBiliPlaybackGuardDom();
    assert.equal(listeners.length, 1);
    assert.equal(listeners[0][0], "play");
    assert.equal(listeners[0][2], true);
    assert.equal(existingPaused, 2);
    const listener = listeners[0][1];
    const newlyCreated = { tagName: "VIDEO", pause: () => { newPaused += 1; } };
    listener({ target: newlyCreated });
    listener({ target: newlyCreated });
    assert.equal(newPaused, 2);
    listener({ target: { tagName: "AUDIO", pause: () => assert.fail("not a video") } });
    assert.doesNotThrow(() => listener({ target: { tagName: "VIDEO", pause: () => { throw new Error("detached"); } } }));
  } finally { if (previous === undefined) delete globalThis.document; else globalThis.document = previous; }
});

test("Bili atomic click rejects video change after successful preflight, without touching send", async () => {
  const previous = globalThis.document;
  let clicks = 0;
  let sendLookups = 0;
  const currentDocument = {
    location: new URL(biliVideoUrl),
    canonical: biliVideoUrl,
    querySelector: (selector) => {
      if (selector === 'link[rel="canonical"]') return { getAttribute: () => currentDocument.canonical };
      if (selector === "bili-comments") {
        sendLookups += 1;
        return { shadowRoot: {
          querySelectorAll: () => [],
          querySelector: () => ({ shadowRoot: { querySelector: () => ({ click: () => { clicks += 1; } }) } }),
        } };
      }
      return null;
    },
  };
  globalThis.document = currentDocument;
  try {
    const page = { evaluate: async (fn) => fn() };
    assert.equal(await assertBiliVideoTarget(page, biliVideoUrl), true);
    for (const [current, canonical] of [
      ["https://www.bilibili.com/video/BV2022Old/", biliVideoUrl],
      [biliVideoUrl, "https://www.bilibili.com/video/BV2022Old/"],
      ["https://www.bilibili.com/video/BV2022Old/", "https://www.bilibili.com/video/BV2022Old/"],
      [biliVideoUrl, ""],
    ]) {
      currentDocument.location = new URL(current);
      currentDocument.canonical = canonical;
      assert.throws(() => clickBiliReplyDom(biliVideoUrl), /已阻止提交点击/);
    }
    assert.equal(clicks, 0);
    assert.equal(sendLookups, 0);
    currentDocument.location = new URL(biliVideoUrl + "?autoplay=0");
    currentDocument.canonical = biliVideoUrl;
    assert.equal(clickBiliReplyDom(biliVideoUrl.slice(0, -1) + "?spm_id_from=333.788"), true);
    assert.equal(clicks, 1);
  } finally { if (previous === undefined) delete globalThis.document; else globalThis.document = previous; }
});

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
  assertReplyRateLimit,
  matchesZhihuTarget,
} from "/Users/sexpistole111/.codex/skills/polyv-lead-auto-reply/scripts/auto_reply.mjs";

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
  assert.match(source, /verifyXhsPostedText\(page, text, author, quote, sourceType\)/);
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

import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import {
  parseArgs,
  isDuplicateReply,
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

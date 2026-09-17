import test from "node:test";
import assert from "node:assert/strict";
import {
  parseArgs,
  isDuplicateReply,
  assertReplyRateLimit,
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

test("CLI requires an explicit Ego Lite TaskSpace", () => {
  assert.throws(() => parseArgs([
    "--platform", "dy",
    "--url", "https://www.douyin.com/video/1",
    "--text", "测试回复",
  ]), /taskspace/);
});

test("duplicate replies are rejected by target and text key", () => {
  const history = [{
    platform: "dy",
    target_url: "https://www.douyin.com/video/1",
    target_author: "用户",
    reply_text: "测试回复",
  }];

  assert.equal(isDuplicateReply(history, {
    platform: "dy",
    url: "https://www.douyin.com/video/1",
    author: "用户",
    text: "测试回复",
  }), true);
});

test("rate limit enforces cooldown and daily cap", () => {
  const now = new Date("2026-09-14T12:00:00.000Z");
  const recent = [{ timestamp: "2026-09-14T11:59:45.000Z", platform: "dy" }];
  assert.throws(() => assertReplyRateLimit(recent, "dy", now), /30秒/);

  const daily = Array.from({ length: 5 }, (_, index) => ({
    timestamp: `2026-09-14T0${index}:00:00.000Z`,
    platform: "dy",
  }));
  assert.throws(() => assertReplyRateLimit(daily, "dy", now), /每日最多5条/);
});

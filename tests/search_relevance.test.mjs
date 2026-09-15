import test from 'node:test';
import assert from 'node:assert/strict';

import { searchRelevance } from '../local_tools/polyv_radar/ego_helpers.mjs';

test('accepts business event results with selection intent', () => {
  const result = searchRelevance('企业直播平台 采购 服务商', '企业直播平台采购方案');
  assert.equal(result.accepted, true);
  assert.ok(result.eventMatches.length > 0);
  assert.ok(result.intentMatches.length > 0);
});

test('rejects unrelated noisy results', () => {
  const result = searchRelevance('员工培训平台 选型 报价', '王者荣耀 KPL 游戏攻略');
  assert.equal(result.accepted, false);
});

test('rejects a generic capability result without an enterprise scene', () => {
  const result = searchRelevance('员工培训平台 选型 报价', '直播平台');
  assert.equal(result.accepted, false);
});

test('accepts overseas multilingual webinar events', () => {
  const result = searchRelevance('海外发布会 多语言直播 方案', '海外发布会多语言直播方案');
  assert.equal(result.accepted, true);
});

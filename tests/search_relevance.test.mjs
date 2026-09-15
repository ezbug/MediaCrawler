import test from 'node:test';
import assert from 'node:assert/strict';

import { cardTitleFromText, filterSearchResults, isExpectedXhsNoteUrl, searchRelevance } from '../local_tools/polyv_radar/ego_helpers.mjs';

test('extracts the title from a Douyin search card', () => {
  const title = cardTitleFromText('01:14\n57\n神鹏品牌全国经销商大会圆满召开\n@郑州三邦机电（周晓峰）\n3周前');
  assert.equal(title, '神鹏品牌全国经销商大会圆满召开');
});

test('does not treat Bilibili metadata as a title', () => {
  assert.equal(cardTitleFromText('1257\n0\n01:12'), '');
});

test('rejects an XHS detail redirect to a different note', () => {
  assert.equal(isExpectedXhsNoteUrl('https://www.xiaohongshu.com/explore/68d922490000000013009d19', '635e3e26000000001601bdac'), false);
  assert.equal(isExpectedXhsNoteUrl('https://www.xiaohongshu.com/explore/635e3e26000000001601bdac', '635e3e26000000001601bdac'), true);
});

test('accepts business event results with selection intent', () => {
  const result = searchRelevance('企业直播平台 采购 服务商', '企业直播平台采购方案');
  assert.equal(result.accepted, true);
  assert.ok(result.eventMatches.length > 0);
  assert.ok(result.intentMatches.length > 0);
});

test('accepts a business event title variant', () => {
  const result = searchRelevance('公司年会直播 平台报价', '年会策划与直播执行');
  assert.equal(result.accepted, true);
});

test('rejects unrelated noisy results', () => {
  const result = searchRelevance('员工培训平台 选型 报价', '王者荣耀 KPL 游戏攻略');
  assert.equal(result.accepted, false);
});

test('rejects a generic capability result without an enterprise scene', () => {
  const result = searchRelevance('员工培训平台 选型 报价', '直播平台');
  assert.equal(result.accepted, false);
});

test('uses an explicit card search text instead of a mixed ancestor snippet', () => {
  const results = filterSearchResults('企业年会直播 策划 平台', [
    { title: '个人生活分享', searchText: '个人生活分享', rawSnippet: '企业年会直播平台策划' },
  ]);
  assert.equal(results.length, 0);
});

test('accepts overseas multilingual webinar events', () => {
  const result = searchRelevance('海外发布会 多语言直播 方案', '海外发布会多语言直播方案');
  assert.equal(result.accepted, true);
});

test('accepts a livestream SDK integration title', () => {
  const result = searchRelevance('直播SDK 商用集成 供应商', '直播APP开发接入美颜SDK详解集成流程');
  assert.equal(result.accepted, true);
});

test('rejects a consumer product launch without an enterprise scene', () => {
  const result = searchRelevance('新品发布会直播 平台报价', '鸿蒙智行春季新品发布会价格');
  assert.equal(result.accepted, false);
});

test('rejects an event title without delivery or project context', () => {
  const result = searchRelevance('公司年会直播 平台报价', '年会唱歌罚4万');
  assert.equal(result.accepted, false);
});

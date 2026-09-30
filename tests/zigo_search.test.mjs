import test from 'node:test';
import assert from 'node:assert/strict';
import { searchRelevance, filterSearchResults } from '../local_tools/polyv_radar/ego_helpers.mjs';

test('sales profile retains sales execution content, not POLYV events', () => {
  assert.equal(searchRelevance('投流线索 跟不上', '投流线索来了，销售跟进不过来', 'zigo_sales').accepted, true);
  assert.equal(searchRelevance('客户跟进', '企业年会直播平台报价', 'zigo_sales').accepted, false);
});
test('GEO requires AI search or brand recommendation, not a sales pain', () => {
  assert.equal(searchRelevance('AI搜索 品牌', '豆包搜索不推荐我们品牌怎么办', 'zigo_geo').accepted, true);
  assert.equal(searchRelevance('GEO优化', '企微客户跟进不过来', 'zigo_geo').accepted, false);
});
test('providers remain content containers, not automatic buyer records', () => {
  assert.equal(searchRelevance('客户跟进', '我们提供企微客户自动跟进系统', 'zigo_sales').accepted, true);
  assert.equal(searchRelevance('AI销售', 'AI作图和AI编程教程', 'zigo_sales').accepted, false);
});
test('filter profile is explicit and mixed ancestor snippets stay excluded', () => {
  assert.equal(filterSearchResults('客户跟进', [{searchText:'客户跟进怎么做'}], 'zigo_sales').length, 1);
  assert.equal(filterSearchResults('客户跟进', [{searchText:'日常分享', rawSnippet:'客户跟进怎么做'}], 'zigo_sales').length, 0);
});

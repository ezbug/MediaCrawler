import test from 'node:test';
import assert from 'node:assert/strict';
import { searchRelevance, filterSearchResults, selectUnseenResults } from '../local_tools/polyv_radar/ego_helpers.mjs';

test('new-source selection skips old IDs without falling back to duplicates', () => {
  const rows=[{id:'old'},{id:'new-1'},{id:'new-2'}];
  assert.deepEqual(selectUnseenResults(rows,1,['old']),[{id:'new-1'}]);
  assert.deepEqual(selectUnseenResults(rows,5,['old','new-1','new-2']),[]);
  assert.deepEqual(selectUnseenResults(rows,2,[]),rows.slice(0,2));
  assert.deepEqual(selectUnseenResults(rows,0,[]),[]);
  assert.throws(()=>selectUnseenResults(rows,2,{old:true}),/array/);
});

test('sales scene containers do not require exact product phrases', () => {
  assert.equal(searchRelevance('销售求助', '新人销售不会谈单求助', 'zigo_sales').accepted, true);
  assert.equal(searchRelevance('销售求助', 'Tob销售陌拜如何开拓客户', 'zigo_sales').accepted, true);
  assert.equal(searchRelevance('销售求助', '销售面试考证培训', 'zigo_sales').accepted, false);
  assert.equal(searchRelevance('销售求助', '销售各种实力排行', 'zigo_sales').accepted, false);
  assert.equal(searchRelevance('GEO', '新人销售不会谈单求助', 'zigo_geo').accepted, false);
});

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

from datetime import datetime, timezone

import pytest

from local_tools.polyv_radar.zigo_discovery import load_registry_queries, run_discovery, screen_record, select_verified, product_evidence
from local_tools.polyv_radar.ego_crawl_all import build_ego_batch_launcher
from local_tools.polyv_radar.config import load_config
from pathlib import Path
import hashlib
import json

NOW = datetime(2026, 9, 30, tzinfo=timezone.utc)


def row(text, **overrides):
    return dict(platform='xhs', content_id='p1', comment_id='c1', author='a',
                author_id='u1', text=text, source_type='comment',
                content_title='AI销售自动跟进教程', url='https://www.xiaohongshu.com/explore/p1',
                published_at='2026-09-29T00:00:00Z', published_at_raw='昨天', **overrides)


def test_two_sales_dimensions_can_qualify_without_standard_procurement_words():
    result = screen_record(row('我们企微客户太多管不过来，销售跟进漏了好多'), 'sales_agent', NOW)
    assert result['decision'] == 'candidate_pending_verification'
    assert set(result['signals']) >= {'business_scene', 'execution_gap'}
    assert result['identity_confidence'] == 'low'


def test_context_does_not_supply_comment_purchase_evidence():
    assert screen_record(row('怎么收费'), 'sales_agent', NOW)['decision'] == 'excluded'


@pytest.mark.parametrize('text', ['我们提供企微客户自动跟进，欢迎咨询', '招聘销售客户跟进专员', '求AI作图工具', 'CRM怎么上线，求系统', 'AI销售真好用'])
def test_noise_excluded(text):
    assert screen_record(row(text), 'sales_agent', NOW)['decision'] == 'excluded'


def test_provider_post_does_not_poison_independent_comment():
    assert screen_record(row('投流客户销售跟不过来，求推荐工具'), 'sales_agent', NOW)['decision'] == 'candidate_pending_verification'


def test_geo_product_does_not_borrow_sales_signals():
    assert screen_record(row('我们企微客户销售跟不过来，求推荐工具'), 'geo', NOW)['decision'] == 'excluded'
    assert screen_record(row('我们品牌豆包搜不到，AI总推荐竞品，有没有工具'), 'geo', NOW)['decision'] == 'candidate_pending_verification'


def test_unknown_or_old_date_never_counts_as_verified():
    unknown = row('我们企微客户跟不过来')
    unknown.update(published_at='', published_at_raw='', create_time=NOW.isoformat())
    assert screen_record(unknown, 'sales_agent', NOW)['decision'] == 'evidence_pending'
    unknown.update(published_at='2021-01-01T00:00:00Z', published_at_raw='2021-01-01')
    assert screen_record(unknown, 'sales_agent', NOW)['decision'] == 'excluded'


def test_no_verified_count_without_author_quote_and_file_evidence():
    candidate = screen_record(row('我们企微客户跟不过来，求推荐工具'), 'sales_agent', NOW)
    assert select_verified([candidate], []) == []
    assert select_verified([candidate], [{'candidate_id':candidate['candidate_id'], 'status':'verified'}]) == []


def test_post_crawl_time_is_not_a_publication_date():
    post = row('我们企微客户跟不过来，求推荐工具')
    post.update(source_type='post', published_at='', published_at_raw='', create_time=NOW.isoformat())
    assert screen_record(post, 'sales_agent', NOW)['freshness'] == 'unknown'


def test_comment_capture_time_is_not_used_when_only_raw_time_exists():
    comment = row('我们企微客户跟不过来，求推荐工具')
    comment.update(source_type='comment', published_at='', published_at_raw='2月前·浙江', create_time=NOW.isoformat())
    assert screen_record(comment, 'sales_agent', NOW)['freshness'] == 'unknown'


def test_product_profile_reaches_ego_node_runtime(tmp_path):
    script = build_ego_batch_launcher(Path('ego_xhs_crawler.mjs'), ['企微 客户'], 5, 30,
                                     tmp_path, 16, tmp_path, product_profile='zigo_sales')
    assert 'process.env.RADAR_PRODUCT_PROFILE = "zigo_sales"' in script


def test_zigo_config_never_expands_polyv_keywords(tmp_path):
    config = tmp_path / 'test.toml'
    config.write_text('[run]\nproduct_profile="zigo_sales"\n[keywords]\nx="客户跟进"\n')
    loaded = load_config(config)
    assert not loaded.taxonomy_enabled
    assert loaded.get_keywords_for_platform('xhs') == {'x':'客户跟进'}


def test_verified_requires_intact_evidence_and_deduplicates_users(tmp_path):
    candidate = screen_record(row('我们企微客户跟不过来，求推荐工具'), 'sales_agent', NOW)
    evidence = tmp_path / 'page.json'
    evidence.write_text(json.dumps({'author':'a', 'quote':candidate['quote']}, ensure_ascii=False))
    check = dict(candidate_id=candidate['candidate_id'], status='verified', container_verified=True,
                 buyer_review_passed=True, verified_at=NOW.isoformat(), matched_author='a',
                 matched_quote=candidate['quote'], content_id='p1', platform='xhs',
                 evidence_path=str(evidence), evidence_sha256=hashlib.sha256(evidence.read_bytes()).hexdigest())
    assert len(select_verified([candidate, candidate], [check])) == 1
    evidence.write_text('modified')
    assert select_verified([candidate], [check]) == []


def test_unknown_identity_cannot_enter_verified_count(tmp_path):
    record = row('企微客户太多销售跟不过来，求推荐工具')
    record.update(author_id='', author_url='')
    candidate = screen_record(record, 'sales_agent', NOW)
    assert select_verified([candidate], [{'candidate_id':candidate['candidate_id'], 'status':'verified'}]) == []


def test_product_source_archive_is_domain_scoped(tmp_path):
    knowledge = tmp_path / 'knowledge'
    knowledge.mkdir()
    (knowledge / 'manifest.json').write_text(json.dumps({'documents':[
        {'source_id':'zigo_sales_agent_202608', 'domain':'sales_agent', 'file_name':'sales.pdf'},
        {'source_id':'zigo_geo_20260721', 'domain':'geo', 'file_name':'geo.pdf'}]}))
    (knowledge / 'chunks.jsonl').write_text('\n'.join(json.dumps(r) for r in [
        dict(source_id='zigo_sales_agent_202608', domain='sales_agent', page=11, text='sales'),
        dict(source_id='zigo_geo_20260721', domain='geo', page=11, text='geo')]))
    assert [p['text'] for p in product_evidence(tmp_path, 'sales_agent')['pages']] == ['sales']


def test_material_registry_queries_are_product_scoped_and_ordered(tmp_path):
    registry = tmp_path / 'keyword-registry.json'
    registry.write_text(json.dumps({
        'version': 'v1',
        'query_registry': [
            {'product_domain': 'geo', 'category': 'query', 'keyword': 'GEO 怎么做'},
            {'product_domain': 'sales_agent', 'category': 'query', 'keyword': '报价后 客户不回'},
            {'product_domain': 'sales_agent', 'category': 'query', 'keyword': '企微 沉睡客户'},
        ]
    }), encoding='utf-8')
    queries, rows, version = load_registry_queries(registry, 'sales_agent', limit=1)
    assert queries == ['报价后 客户不回']
    assert rows[0]['product_domain'] == 'sales_agent'
    assert version == 'v1'


def test_discovery_replay_writes_product_scoped_plan_and_database(tmp_path):
    knowledge = tmp_path / 'knowledge'
    knowledge.mkdir()
    (knowledge / 'manifest.json').write_text(json.dumps({'documents': [
        {'source_id': 'sales-doc', 'domain': 'sales_agent', 'file_name': 'sales.pdf'}
    ]}), encoding='utf-8')
    (knowledge / 'chunks.jsonl').write_text(json.dumps({
        'source_id': 'sales-doc', 'domain': 'sales_agent', 'page': 4, 'text': 'sales evidence'
    }) + '\n', encoding='utf-8')
    data_root = tmp_path / 'data' / 'sales_agent'
    raw = data_root / 'raw' / 'replay-1' / 'xhs' / '01-query'
    raw.mkdir(parents=True)
    (raw / 'xhs_contents.jsonl').write_text(json.dumps({
        'platform': 'xhs', 'content_id': 'p1', 'title': '销售跟进', 'text': '客户跟进问题',
        'url': 'https://example.test/p1', 'author': '用户', 'author_id': 'u1',
        'published_at': '2026-09-29T00:00:00Z', 'source_keyword': '报价后 客户不回'
    }) + '\n', encoding='utf-8')
    (raw / 'xhs_comments.jsonl').write_text(json.dumps({
        'platform': 'xhs', 'content_id': 'p1', 'comment_id': 'c1',
        'text': '我们公司报价后客户不回，求推荐自动跟进工具', 'author': '买方',
        'author_id': 'u2', 'source_type': 'comment', 'published_at': '2026-09-29T00:00:00Z'
    }) + '\n', encoding='utf-8')
    config = tmp_path / 'zigo.toml'
    config.write_text(
        '[run]\nproduct_profile="zigo_sales"\n'
        f'data_root="{data_root}"\nplatforms=["xhs"]\n'
        '[keywords]\nquery="旧词"\n', encoding='utf-8'
    )
    registry = tmp_path / 'registry.json'
    registry.write_text(json.dumps({'version': 'v-test', 'query_registry': [
        {'product_domain': 'sales_agent', 'category': 'query', 'keyword': '报价后 客户不回', 'source_pages': [4]},
        {'product_domain': 'geo', 'category': 'query', 'keyword': 'GEO 怎么做'},
    ]}), encoding='utf-8')

    result = run_discovery(config, 'sales_agent', 'replay-1', keyword_registry=registry,
                           product_root=tmp_path, query_limit=1)
    plan = json.loads((data_root / 'reports' / 'replay-1' / 'query-plan.json').read_text())
    assert result['zigo_db'].endswith('/data/radar.sqlite3')
    assert plan['queries'] == ['报价后 客户不回']
    assert plan['registry_version'] == 'v-test'
    assert Path(result['zigo_db']).is_file()

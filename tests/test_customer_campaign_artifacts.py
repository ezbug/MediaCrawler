import csv
import json
from types import SimpleNamespace

import pytest

from local_tools.polyv_radar.customer_campaign_artifacts import run_customer_campaign


def args(**kwargs):
    return SimpleNamespace(campaign_id="test-training", sector="企业管理培训与内训服务机构",
                           action=kwargs.get("action", "report"), input=kwargs.get("input"))


def test_import_is_idempotent_and_exports_counted_records(tmp_path):
    config = SimpleNamespace(product_profile="polyv", data_root=tmp_path)
    source = tmp_path / "input.json"
    source.write_text(json.dumps([dict(company_name="=Training", business_type="training_provider",
        scenario="线上课程", quote="我们提供企业内训", source_url="https://training.test/",
        contact_entry_url="https://training.test/contact", identity_status="verified",
        official_domain="training.test", source_verified=True, fit_reason="需要课程交付能力")]))
    first = run_customer_campaign(config, args(action="import", input=source))
    second = run_customer_campaign(config, args(action="import", input=source))
    assert first == second
    assert second["qualified_companies"] == 1
    assert second["contacted_companies"] == second["effective_exchanges"] == 0
    directory = tmp_path / "campaigns" / "test-training"
    ledger = json.loads((directory / "company-ledger.json").read_text())
    with (directory / "customer-followup.csv").open(encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == len(ledger) == 1
    assert rows[0]["company_name"] == "'=Training"
    assert "=Training" in (directory / "customer-dashboard.html").read_text()


@pytest.mark.parametrize("profile,campaign,action", [
    ("geo", "training", "report"), ("polyv", "../outside", "report"),
    ("polyv", "training", "import"), ("polyv", "training", "exchange"),
])
def test_invalid_inputs_do_not_create_database(tmp_path, profile, campaign, action):
    config = SimpleNamespace(product_profile=profile, data_root=tmp_path)
    request = args(action=action)
    request.campaign_id = campaign
    with pytest.raises(ValueError):
        run_customer_campaign(config, request)
    assert not (tmp_path / "radar.sqlite3").exists()

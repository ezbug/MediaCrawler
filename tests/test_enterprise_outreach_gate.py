from datetime import date

from local_tools.enterprise_data.outreach_gate import audit_batch, audit_email, extract_events

DAY = date(2026, 10, 13)
TARGET = {"id": "haier", "name": "海尔智家", "aliases": ["海尔"],
          "source_domains": ["haier.com", "eastmoney.com"], "mail_domains": ["haier.com"]}


def evidence(text="海尔智家将于2026年10月16日举行半年度业绩说明会。"):
    capture = {"url": "https://www.haier.com/notice", "text": text,
               "title": "公告", "captured_at": "2026-10-13T09:00:00+08:00"}
    return extract_events(capture, TARGET, DAY)


def mail(events=None):
    event = (events or evidence())[0]
    hook = f"预祝海尔智家于{event['event_date']}举办的{event['event_name']}顺利举行。"
    return {"company_id": "haier", "company": "海尔智家", "event_id": event["event_id"],
            "event_date": event["event_date"], "event_name": event["event_name"],
            "business_line": event["business_line"], "to": "ir@haier.com",
            "recipient_role": "ir", "subject": "关于投资者交流活动的建议",
            "hook": hook, "body": hook + "可考虑将远程交流与回放相结合。"}


def test_normal_email_passes():
    assert audit_email(mail(), evidence(), [TARGET], DAY)["status"] == "passed"


def test_haier_incident_blocks_training_recipient_but_preserves_facts():
    events = evidence("海尔智家已于2026年8月28日发布半年度报告。海尔智家计划于2026年10月16日举行半年度业绩说明会。")
    assert len(events) == 1 and events[0]["event_date"] == "2026-10-16"
    request = mail(events)
    request.update(to="training@haier.com", recipient_role="training")
    result = audit_email(request, events, [TARGET], DAY)
    assert result["status"] == "blocked"
    assert "recipient_function_mismatch" in result["reasons"]


def test_test_marker_blocks():
    request = mail()
    request["body"] += "本稿为测试邮件"
    assert "template_or_internal_marker" in audit_email(request, evidence(), [TARGET], DAY)["reasons"]


def test_cross_company_blocks():
    other = {**TARGET, "id": "midea", "name": "美的", "mail_domains": ["midea.com"]}
    request = mail()
    request.update(company_id="midea", company="美的", to="ir@midea.com")
    assert "company_event_mismatch" in audit_email(request, evidence(), [TARGET, other], DAY)["reasons"]


def test_irrelevant_event_blocks():
    events = evidence("海尔智家计划于2026年10月16日召开股东大会。")
    assert "business_irrelevant_or_mismatch" in audit_email(mail(events), events, [TARGET], DAY)["reasons"]


def test_changed_date_in_body_blocks():
    request = mail()
    request["hook"] = request["hook"].replace("10-16", "10-19")
    request["body"] = request["hook"]
    assert "hook_text_date_mismatch" in audit_email(request, evidence(), [TARGET], DAY)["reasons"]


def test_future_window_and_company_deduplication():
    assert not evidence("海尔智家将于2026年10月12日举行培训。")
    assert not evidence("海尔智家将于2026年12月13日举行培训。")
    assert len(evidence("海尔智家将于2026年10月16日举行培训。海尔智家将于2026年10月16日举行培训。")) == 1
    assert not evidence("美的将于2026年10月16日举行培训。")


def test_untrusted_url_and_date_ambiguity_do_not_create_events():
    assert not extract_events({"url": "https://haier.com.evil.example/", "text": "海尔智家2026年10月16日举行培训。"}, TARGET, DAY)
    assert not evidence("海尔智家2026年8月28日发布报告，并于2026年10月16日举行说明会。")


def test_tampered_source_and_stale_capture_block():
    events = evidence()
    events[0]["capture"]["text"] = "无相关活动"
    assert "source_integrity_mismatch" in audit_email(mail(events), events, [TARGET], DAY)["reasons"]
    events = evidence()
    events[0]["capture"]["captured_at"] = "2026-10-10T09:00:00+08:00"
    assert "source_stale_recollect_required" in audit_email(mail(events), events, [TARGET], DAY)["reasons"]


def test_manual_queue_preserves_failed_email(tmp_path):
    request = mail()
    request["body"] += "{{COMPANY}}"
    result = audit_batch([mail(), request], evidence(), [TARGET], tmp_path, DAY)
    assert result["passed"] == result["blocked"] == 1
    assert "{{COMPANY}}" in (tmp_path / "manual-confirmation-queue.json").read_text()


def test_unknown_role_and_email_domain_block():
    for address in ("contact@haier.com", "ir@other.example"):
        request = mail()
        request["to"] = address
        assert "recipient_function_mismatch" in audit_email(request, evidence(), [TARGET], DAY)["reasons"]


def test_announcement_title_can_attribute_company_pronoun_but_listing_cannot():
    capture = {"url": "https://www.haier.com/notice", "title": "海尔智家关于召开业绩说明会的公告",
               "text": "公司计划于2026年10月16日举行业绩说明会。",
               "captured_at": "2026-10-13T09:00:00+08:00"}
    events = extract_events(capture, TARGET, DAY)
    assert events[0]["company_attribution"] == "issuer_announcement_title"
    assert audit_email(mail(events), events, [TARGET], DAY)["status"] == "passed"
    capture["title"] = "海尔活动列表"
    assert not extract_events(capture, TARGET, DAY)


def test_announcement_meeting_time_does_not_parse_clock_range_as_date():
    capture = {"url": "https://www.haier.com/notice", "title": "海尔智家关于召开业绩说明会的公告",
               "text": "会议召开时间：2026 年 10 月 16 日（星期五）14:00-15:00\n",
               "captured_at": "2026-10-13T09:00:00+08:00"}
    assert extract_events(capture, TARGET, DAY)[0]["event_date"] == "2026-10-16"


def test_missing_template_fields_block_but_free_trial_copy_passes():
    for marker in ("{hook}", "[公司名]", "测试版"):
        request = mail()
        request["body"] += marker
        assert "template_or_internal_marker" in audit_email(request, evidence(), [TARGET], DAY)["reasons"]
    request = mail()
    request["body"] += "免费开通测试账号"
    assert audit_email(request, evidence(), [TARGET], DAY)["status"] == "passed"


def test_previous_block_does_not_self_release_when_evidence_changes(tmp_path):
    request = mail()
    assert audit_batch([request], [], [TARGET], tmp_path, DAY)["blocked"] == 1
    result = audit_batch([request], evidence(), [TARGET], tmp_path, DAY)
    assert result["blocked"] == 1
    assert "previously_blocked_requires_user_confirmation" in result["checks"][0]["reasons"]


def test_no_hook_email_passes_with_valid_role_and_business_line():
    request = {"company_id": "haier", "company": "海尔智家", "to": "training@haier.com",
               "recipient_role": "training", "subject": "关于经销商培训的三点反馈",
               "business_line": "enterprise_training", "hook": "", "body": "负责培训的老师，您好：\n\n我们在家电行业服务过 A.O.史密斯、宝马、蔚来。"}
    result = audit_email(request, [], [TARGET], DAY)
    assert result["status"] == "passed" and result["hook_status"] == "none"


def test_no_hook_email_with_wrong_domain_or_business_line_blocks():
    base = {"company_id": "haier", "company": "海尔智家", "to": "training@haier.com",
            "recipient_role": "training", "subject": "主题", "business_line": "enterprise_training",
            "hook": "", "body": "正文"}
    assert "recipient_function_mismatch" in audit_email({**base, "to": "training@other.com"}, [], [TARGET], DAY)["reasons"]
    assert "business_line_invalid" in audit_email({**base, "business_line": "unknown"}, [], [TARGET], DAY)["reasons"]

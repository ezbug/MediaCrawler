from __future__ import annotations

import pytest

from local_tools.enterprise_data.job_collect import build_command, collect_jobs, parse_collector_output


def test_build_command_requires_taskspace():
    command = build_command(taskspace=3, url="https://example.com/jobs", platform="boss", scrolls=2, max_jobs=10)
    assert command[0].endswith("ego_jobs")
    assert command[command.index("--taskspace") + 1] == "3"
    assert command[command.index("--platform") + 1] == "boss"
    with pytest.raises(ValueError):
        build_command(taskspace=0, url="https://example.com/jobs")


def test_parse_collector_output_ignores_leading_logs():
    stdout = 'noise line\n{"jobs":[{"platform":"boss","platform_job_id":"a","job_title":"Java 工程师"}],"_extraction":{"url":"https://x","warnings":[]}}'
    payload = parse_collector_output(stdout, "c1")
    assert payload["company_id"] == "c1"
    assert len(payload["jobs"]) == 1
    assert payload["jobs"][0]["job_title"] == "Java 工程师"
    with pytest.raises(ValueError):
        parse_collector_output("no json here", "c1")


def test_collect_jobs_reads_json_from_stderr(tmp_path):
    class Completed:
        returncode = 0
        stdout = ""
        stderr = '[ego-browser:notice] update available\n{"jobs":[{"platform":"boss","platform_job_id":"z","job_title":"Z"}],"_extraction":{"url":"u"}}'

    def runner(command, **kwargs):
        return Completed()

    payload = collect_jobs(company_id="c1", url="https://x", taskspace=3, runner=runner)
    assert payload["jobs"][0]["job_title"] == "Z"


def test_collect_jobs_runs_wrapper_and_writes_output(tmp_path):
    class Completed:
        returncode = 0
        stdout = '{"jobs":[{"platform":"boss","platform_job_id":"a","job_title":"X"}],"_extraction":{"url":"u","warnings":[]}}'
        stderr = ""

    calls = []

    def runner(command, **kwargs):
        calls.append(command)
        return Completed()

    output = tmp_path / "jobs.json"
    payload = collect_jobs(
        company_id="c1", url="https://x", taskspace=3, platform="boss", output=output, runner=runner,
    )
    assert payload["jobs"][0]["job_title"] == "X"
    assert output.exists()
    assert calls and calls[0][0].endswith("ego_jobs")


def test_collect_jobs_raises_on_hard_failure():
    class Failed:
        returncode = 1
        stdout = ""
        stderr = "boom"

    def runner(command, **kwargs):
        return Failed()

    with pytest.raises(RuntimeError):
        collect_jobs(company_id="c1", url="https://x", taskspace=3, runner=runner)


def test_employer_filter_drops_staffing_agency_jobs():
    class Completed:
        returncode = 0
        stdout = ""
        stderr = (
            '{"jobs":['
            '{"platform":"boss","platform_job_id":"a","job_title":"5G研发工程师","employer_name":"中兴通讯股份有限公司"},'
            '{"platform":"boss","platform_job_id":"b","job_title":"中兴通讯电子厂急招普工","employer_name":"某某人力资源有限公司"},'
            '{"platform":"boss","platform_job_id":"c","job_title":"测试工程师","employer_name":""}'
            '],"_extraction":{"url":"u","warnings":[]}}'
        )

    def runner(command, **kwargs):
        return Completed()

    payload = collect_jobs(company_id="zte", url="https://x", taskspace=3, employer_filter="中兴通讯", runner=runner)
    kept_ids = [job["platform_job_id"] for job in payload["jobs"]]
    # 中介公司发的中兴普工贴被剔除；雇主为空但标题含关键词的保留
    assert kept_ids == ["a", "c"]
    assert payload["_extraction"]["employer_filter"] == "中兴通讯"
    assert any("剔除 1 条" in warning for warning in payload["_extraction"]["warnings"])

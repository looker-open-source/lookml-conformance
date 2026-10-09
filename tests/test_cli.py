from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from lookml_conformance.cli import EXIT_FAILURES, EXIT_OK, EXIT_USAGE, main
from tests.conftest import MakeCase

ADAPTER = """\
import json, sys
table = {table!r}
print(json.dumps({{"adapter": "fake", "version": "1",
                   "models": {{"m": {{"views": {{"orders": {{"sql_table_name": table}}}}}}}}}}))
"""


@pytest.fixture
def cases_dir(make_case: MakeCase, tmp_path: Path) -> Path:
    make_case(id="r01_a", title="First")
    make_case(id="r02_b", title="Second")
    return tmp_path / "cases"


def fake_adapter(tmp_path: Path, table: str, name: str = "fake.py") -> str:
    path = tmp_path / name
    path.write_text(ADAPTER.format(table=table), encoding="utf-8")
    return f"{sys.executable} {path}"


def test_list(cases_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--cases", str(cases_dir), "list", "--only", "r02"]) == EXIT_OK

    out = capsys.readouterr().out
    assert "r02_b" in out
    assert "Second" in out
    assert "r01_a" not in out


def test_validate(cases_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--cases", str(cases_dir), "validate"]) == EXIT_OK
    assert capsys.readouterr().out == "2 cases are valid\n"


def test_validate_reports_invalid_cases(
    make_case: MakeCase, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    make_case(title="")

    assert main(["--cases", str(tmp_path / "cases"), "validate"]) == EXIT_USAGE
    assert "'title' must be a non-empty string" in capsys.readouterr().err


def test_run_with_a_passing_command(
    cases_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    command = fake_adapter(tmp_path, "raw.orders")

    code = main(["--cases", str(cases_dir), "run", "--command", command, "--name", "mine", "-j", "2"])

    assert code == EXIT_OK
    captured = capsys.readouterr()
    assert captured.out.splitlines()[-1].split() == ["mine", "1", "2", "/", "2", "2", "/", "2"]
    assert "pass  r01_a" in captured.err


def test_run_writes_reports_and_fails(
    cases_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "out"

    code = main(
        [
            "--cases",
            str(cases_dir),
            "run",
            "--quiet",
            "--only",
            "r01",
            "--command",
            fake_adapter(tmp_path, "wrong"),
            "--json",
            str(out / "s.json"),
            "--markdown",
            str(out / "s.md"),
        ]
    )

    assert code == EXIT_FAILURES
    assert capsys.readouterr().err.splitlines() == [f"wrote {out / 's.json'}", f"wrote {out / 's.md'}"]
    data = json.loads((out / "s.json").read_text(encoding="utf-8"))
    assert [result["case"] for result in data["results"]] == ["r01_a"]
    assert data["results"][0]["verdicts"]["local"]["outcome"] == "fail"
    assert "expected 'raw.orders', got 'wrong'" in (out / "s.md").read_text(encoding="utf-8")


def test_run_with_registry_and_adapter_filter(
    cases_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    registry = tmp_path / "adapters.json"
    adapters = [
        {"name": "good", "label": "Good", "command": fake_adapter(tmp_path, "raw.orders", "good.py").split()},
        {"name": "bad", "command": fake_adapter(tmp_path, "wrong", "bad.py").split()},
    ]
    registry.write_text(json.dumps({"adapters": adapters}), encoding="utf-8")

    code = main(["--cases", str(cases_dir), "run", "-q", "--registry", str(registry), "--adapter", "good"])

    assert code == EXIT_OK
    assert "bad" not in capsys.readouterr().out


def test_run_with_unknown_adapter(
    cases_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    registry = tmp_path / "adapters.json"
    registry.write_text(json.dumps({"adapters": []}), encoding="utf-8")

    assert (
        main(["--cases", str(cases_dir), "run", "--registry", str(registry), "--adapter", "x"]) == EXIT_USAGE
    )
    assert "unknown adapter(s) x" in capsys.readouterr().err


def test_run_without_matching_cases(cases_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--cases", str(cases_dir), "run", "--only", "zzz", "--command", "true"]) == EXIT_USAGE
    assert "no cases selected" in capsys.readouterr().err


def test_report_renders_markdown_with_labels(
    cases_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    scorecard = tmp_path / "s.json"
    main(
        [
            "--cases",
            str(cases_dir),
            "run",
            "-q",
            "--command",
            fake_adapter(tmp_path, "raw.orders"),
            "--name",
            "fake",
            "--json",
            str(scorecard),
        ]
    )
    registry = tmp_path / "adapters.json"
    registry.write_text(json.dumps({"adapters": [{"name": "fake", "label": "Fake Tool", "command": ["x"]}]}))
    capsys.readouterr()

    assert main(["report", str(scorecard), "--registry", str(registry)]) == EXIT_OK
    assert "| Fake Tool | `1` |" in capsys.readouterr().out


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["--version"])
    assert capsys.readouterr().out.startswith("lookml-conformance ")


def test_catalog_writes_and_checks(
    cases_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "CASES.md"

    assert main(["--cases", str(cases_dir), "catalog", "--check", "-o", str(output)]) == EXIT_FAILURES
    assert main(["--cases", str(cases_dir), "catalog", "-o", str(output)]) == EXIT_OK
    assert main(["--cases", str(cases_dir), "catalog", "--check", "-o", str(output)]) == EXIT_OK
    assert "### `r01_a`" in output.read_text(encoding="utf-8")
    assert "out of date" in capsys.readouterr().err


def test_check_citations(
    cases_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    page = "<p>In most cases a refinement will override the original settings of an object.</p>"
    monkeypatch.setattr("lookml_conformance.citations.fetch_url", lambda url: page)

    assert main(["--cases", str(cases_dir), "check-citations"]) == EXIT_OK
    assert capsys.readouterr().out == "2 of 2 citations found\n"

    monkeypatch.setattr("lookml_conformance.citations.fetch_url", lambda url: "<p>nothing</p>")
    assert main(["--cases", str(cases_dir), "check-citations"]) == EXIT_FAILURES
    assert "r01_a: quote not found on the page" in capsys.readouterr().out


def test_setup_uses_the_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    registry = tmp_path / "adapters.json"
    adapters = [
        {"name": "a", "command": ["x"], "install": {"npm": "a@1"}},
        {"name": "b", "command": ["x"], "install": {"npm": "b@1"}},
    ]
    registry.write_text(json.dumps({"adapters": adapters}), encoding="utf-8")
    calls: list[tuple[list[str], Path, str]] = []
    monkeypatch.setattr(
        "lookml_conformance.cli.setup",
        lambda selected, root, python: calls.append(([a.name for a in selected], root, python)),
    )

    assert main(["setup", "--registry", str(registry), "--python", "python3.11", "b"]) == EXIT_OK
    assert calls == [(["b"], tmp_path.resolve(), "python3.11")]


def test_setup_reports_bad_registry_entries(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    registry = tmp_path / "adapters.json"
    registry.write_text(json.dumps({"adapters": [{"name": "a", "command": ["x"]}]}), encoding="utf-8")

    assert main(["setup", "--registry", str(registry)]) == EXIT_USAGE
    assert "no 'install' entry" in capsys.readouterr().err

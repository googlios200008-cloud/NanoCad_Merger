from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path

import pytest

from nanomerger.cli import main
from nanomerger.converters import OdaConverter, find_oda
from nanomerger.errors import CancelledError, ConversionError
from nanomerger.publishing import publish


def test_find_oda_explicit_and_env(tmp_path, monkeypatch):
    exe = tmp_path / "ODAFileConverter"
    exe.touch()
    assert find_oda(exe) == exe.resolve()
    monkeypatch.setenv("NANOMERGER_ODA", str(exe))
    assert find_oda() == exe.resolve()
    assert find_oda(tmp_path / "missing") is None


def test_oda_argument_contract_and_missing_output(tmp_path, monkeypatch):
    exe = tmp_path / "ODAFileConverter"
    exe.touch()
    converter = OdaConverter(exe)
    calls = []

    def fake_run(args, *, cancel):
        calls.append(args)
        return "oda log"

    monkeypatch.setattr(converter, "_run", fake_run)
    source = tmp_path / "A1.dwg"
    source.write_bytes(b"not a real dwg; converter is mocked")
    with pytest.raises(ConversionError, match="не создал DXF"):
        converter.read_drawings([source], tmp_path / "out")
    args = calls[0]
    assert args[2:] == ["ACAD2018", "DXF", "0", "1", "*"]
    assert Path(args[0]).is_dir() is False  # staging directory is cleaned after failure


def test_oda_timeout_and_cancel_use_real_child_process(tmp_path):
    script = tmp_path / "slow.py"
    script.write_text("import time; time.sleep(30)\n", encoding="utf-8")
    converter = OdaConverter(sys.executable, timeout_seconds=0.3)
    # Use the real process supervisor with a Python child instead of proprietary ODA.
    converter.executable = Path(sys.executable)
    with pytest.raises(ConversionError, match="не завершил"):
        converter._run([str(script)], cancel=None)
    event = threading.Event()
    timer = threading.Timer(0.2, event.set)
    timer.start()
    try:
        with pytest.raises(CancelledError):
            converter._run([str(script)], cancel=event)
    finally:
        timer.cancel()


def test_publish_rolls_back_existing_outputs(tmp_path, monkeypatch):
    first, second = tmp_path / "a.txt", tmp_path / "b.txt"
    first.write_text("old-a")
    second.write_text("old-b")
    new_first, new_second = tmp_path / "new-a", tmp_path / "new-b"
    new_first.write_text("new-a")
    new_second.write_text("new-b")
    real_replace = os.replace
    calls = 0

    def flaky_replace(src, dst):
        nonlocal calls
        calls += 1
        if Path(dst) == second and Path(src).name == "new-b":
            raise OSError("simulated locked output")
        return real_replace(src, dst)

    monkeypatch.setattr("nanomerger.publishing.os.replace", flaky_replace)
    with pytest.raises(ConversionError, match="закройте файлы"):
        publish({first: new_first, second: new_second}, overwrite=True)
    assert first.read_text() == "old-a"
    assert second.read_text() == "old-b"


def test_cli_scan_json(tmp_path, capsys):
    (tmp_path / "S2.dwg").touch()
    (tmp_path / "S10.dwg").touch()
    assert main(["scan", str(tmp_path), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert [f["number"] for f in data["files"]] == [2, 10]


def test_cli_dxf_merge_and_error_json(dxf_folder, tmp_path, capsys):
    out = tmp_path / "cli-out"
    code = main(
        [
            "merge",
            str(dxf_folder),
            "-o",
            str(out),
            "--input-format",
            "dxf",
            "--output-format",
            "dxf",
            "--json",
            "--quiet",
        ]
    )
    captured = capsys.readouterr()
    assert code == 0
    data = json.loads(captured.out)
    assert Path(data["pdf_path"]).exists()
    assert data["dwg_path"] is None
    assert main(["merge", str(tmp_path / "missing"), "--json"]) == 2
    assert json.loads(capsys.readouterr().err)["code"] == 2


def test_cli_doctor_json(capsys):
    assert main(["doctor", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["packages"]["ezdxf"] == "1.4.3"

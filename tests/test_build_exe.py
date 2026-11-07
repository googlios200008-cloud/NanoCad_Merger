from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("build_exe", ROOT / "build_exe.py")
build_exe = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(build_exe)


def test_python_version_gate():
    build_exe.check_python((3, 11))
    build_exe.check_python((3, 13))
    with pytest.raises(SystemExit, match="Python"):
        build_exe.check_python((3, 9))
    with pytest.raises(SystemExit, match="Python"):
        build_exe.check_python((3, 14))


def test_build_command_collects_lazy_imports_and_resources():
    args = build_exe.parse_args([])
    command = build_exe.build_command(Path("python"), args)
    assert "--onedir" in command
    assert "--windowed" in command
    assert "--noupx" in command
    assert "--collect-all" in command and "ezdxf" in command and "matplotlib" in command
    assert "--hidden-import" in command and "nanomerger.merger" in command
    assert "PySide6.QtSvg" in command
    assert command[-1] == str(build_exe.ENTRY)
    assert build_exe.expected_exe(args) == ROOT / "dist" / "NanoMerger" / "NanoMerger.exe"


def test_onefile_and_console_options():
    args = build_exe.parse_args(["--onefile", "--console", "--no-clean"])
    command = build_exe.build_command(Path("python"), args)
    assert "--onefile" in command and "--onedir" not in command
    assert "--console" in command and "--windowed" not in command
    assert "--clean" not in command
    assert build_exe.expected_exe(args) == ROOT / "dist" / "NanoMerger.exe"


def test_dry_run_does_not_create_environment(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(build_exe, "BUILD_VENV", tmp_path / "missing-venv")
    assert build_exe.main(["--dry-run", "--use-current-env"]) == 0
    assert not (tmp_path / "missing-venv").exists()
    assert "PyInstaller" in capsys.readouterr().out


def test_actual_build_requires_windows(monkeypatch, capsys):
    monkeypatch.setattr(sys, "platform", "linux")
    assert build_exe.main([]) == 2
    assert "Windows" in capsys.readouterr().err


def test_skip_install_missing_environment_is_actionable(tmp_path, monkeypatch):
    monkeypatch.setattr(build_exe, "BUILD_VENV", tmp_path / "missing-venv")
    args = build_exe.parse_args(["--skip-install"])
    with pytest.raises(SystemExit, match="skip-install"):
        build_exe.ensure_build_python(args)


def test_distribution_notes_mention_external_oda(tmp_path):
    exe = tmp_path / "NanoMerger" / "NanoMerger.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"placeholder")
    args = build_exe.parse_args([])
    build_exe.write_distribution_notes(exe, args)
    notes = (exe.parent / "START_HERE.txt").read_text(encoding="utf-8")
    assert "ODA File Converter" in notes
    assert (exe.parent / "THIRD_PARTY_NOTICES.md").exists()


def test_windows_default_build_environment_is_short(tmp_path):
    root = tmp_path / ("very-long-project-" * 8)
    venv = build_exe.default_build_venv(
        windows=True, root=root, local_app_data=tmp_path / "Local", version=(3, 12), machine="AMD64"
    )
    assert venv.parent == tmp_path / "Local" / "NanoMerger" / "BuildEnvs"
    assert venv.name.startswith("py312-amd64-")
    assert len(str(venv)) < len(str(root / ".venv-build"))


def test_recreate_refuses_non_venv_directory(tmp_path, monkeypatch):
    fake = tmp_path / "not-a-venv"
    fake.mkdir()
    monkeypatch.setattr(build_exe, "BUILD_VENV", fake)
    args = build_exe.parse_args(["--recreate-venv"])
    with pytest.raises(SystemExit, match="pyvenv.cfg"):
        build_exe.ensure_build_python(args)
    assert fake.exists()

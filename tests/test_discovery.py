from pathlib import Path

import pytest

from nanomerger.discovery import parse_name, scan_folder
from nanomerger.errors import InputError


@pytest.mark.parametrize(
    ("name", "prefix", "number"),
    [
        ("Sheet1.dwg", "Sheet", 1),
        ("Sheet_002.dwg", "Sheet", 2),
        ("Sheet-10.DWG", "Sheet", 10),
        ("Sheet 3.dwg", "Sheet", 3),
        ("EPLAN_2024_4.dwg", "EPLAN_2024", 4),
        ("Без номера.dwg", "Без номера", None),
    ],
)
def test_parse_name(name, prefix, number):
    item = parse_name(Path(name))
    assert item.prefix == prefix
    assert item.number == number


def test_numeric_not_lexicographic(tmp_path):
    for name in ["Sheet10.dwg", "Sheet2.dwg", "Sheet1.dwg", "Sheet003.dwg", "ignore.txt"]:
        (tmp_path / name).touch()
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "Sheet0.dwg").touch()
    files, warnings = scan_folder(tmp_path)
    assert [f.number for f in files] == [1, 2, 3, 10]
    assert any("пропущены" in w for w in warnings)


def test_duplicate_number_is_error(tmp_path):
    (tmp_path / "Sheet1.dwg").touch()
    (tmp_path / "Sheet_001.dwg").touch()
    with pytest.raises(InputError, match="одинаковые номера"):
        scan_folder(tmp_path)


def test_unnumbered_after_numbered_and_gap_warning(tmp_path):
    for name in ["Sheet_extra.dwg", "Sheet5.dwg", "Sheet1.dwg"]:
        (tmp_path / name).touch()
    files, warnings = scan_folder(tmp_path)
    assert [f.name for f in files] == ["Sheet1.dwg", "Sheet5.dwg", "Sheet_extra.dwg"]
    assert any("пропущены" in w for w in warnings)
    assert any("нет конечного номера" in w for w in warnings)


def test_empty_folder(tmp_path):
    with pytest.raises(InputError, match="нет файлов"):
        scan_folder(tmp_path)

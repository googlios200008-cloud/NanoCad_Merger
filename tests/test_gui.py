import pytest

from nanomerger import gui


def test_gui_dependency_is_optional_and_actionable():
    if gui.QT_IMPORT_ERROR is None:
        pytest.skip("Qt is installed; missing-dependency branch is not applicable")
    from nanomerger.errors import DependencyError

    with pytest.raises(DependencyError, match="gui"):
        gui.require_qt()


@pytest.mark.skipif(gui.QT_IMPORT_ERROR is not None, reason="Qt runtime unavailable")
def test_window_constructs_offscreen(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    window = gui.NanoMergerWindow()
    window.oda_edit.setText(str(tmp_path / "missing"))
    assert window.table.columnCount() == 4
    assert window.start_button.text().startswith("Объединить")
    window.close()
    app.processEvents()

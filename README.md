# NanoMerger

**NanoMerger** — Python-утилита для типового сценария после экспорта EPLAN: в папке лежат `Scheme1.dwg`, `Scheme2.dwg`, … `Scheme10.dwg`, а заказчику нужен **один DWG** и **один многостраничный PDF**.

Утилита работает в трёх режимах:

- **библиотека** для встраивания в Engi или другой Python-проект;
- **CLI** для пакетной автоматизации;
- **настольное приложение** на PySide6.

> Статус: **0.1.0, первая рабочая версия / alpha**. Ядро, сортировка, размещение, листы, DXF-цикл и PDF покрыты автоматическими тестами. Полный DWG-цикл использует установленный **ODA File Converter**; проприетарный конвертер не входит в репозиторий и должен быть проверен на вашем контрольном комплекте EPLAN. PDF в этой версии — векторная визуализация геометрии, а не native-печать CAD с CTB/STB.

## Что делает версия 0.1

1. Сканирует **одну выбранную папку без рекурсии**.
2. Сортирует по конечному числу: `Scheme2.dwg` идёт раньше `Scheme10.dwg`; допускаются разделители `_`, `-`, пробел и ведущие нули.
3. Читает DWG через ODA File Converter во временный DXF.
4. Переносит **пространство модели** каждого файла в отдельный блок объединённого документа. Конфликтующие имена слоёв, блоков, стилей и типов линий изолируются, а не переиспользуются из другого файла.
5. Располагает чертежи **слева направо в одну ленту** по умолчанию. Можно задать сетку с несколькими столбцами и зазор в миллиметрах.
6. Создаёт **отдельный лист CAD на каждый исходный файл** с видовым экраном на соответствующий участок модели. Имена и порядок вкладок соответствуют порядку файлов.
7. Записывает настоящий DWG через ODA, затем читает его обратно.
8. Создаёт многостраничный PDF **из сохранённого объединённого CAD-файла**: одна страница на лист, с размером листа и областью видового экрана.
9. Публикует комплект только после успешного создания CAD, PDF и JSON-отчёта. Исходники не изменяются.

## Важные границы реализации

### DWG

`ezdxf` работает с DXF. Для DWG NanoMerger вызывает отдельное приложение **ODA File Converter**: DWG → DXF → объединение → DXF → DWG. Это не переименование DXF в DWG. Конвертер нужно установить отдельно и принять его лицензию: <https://www.opendesign.com/guestfiles/oda_file_converter>.

В этой песочнице ODA не установлен, поэтому здесь проверен DXF-цикл, контракт адаптера, таймауты и отмена процесса. Реальный DWG-цикл запускается на машине с ODA; см. `docs/ACCEPTANCE.md`.

### Что копируется

Версия 0.1 намеренно ограничена **пространством модели** исходных файлов. Это соответствует типичному экспорту EPLAN, где рамка и схема находятся в модели. Объекты исходного Paper Space — например отдельный штамп или подписи на листе — **не копируются**; размер бумаги исходного листа учитывается. Если такие объекты есть, программа выдаёт предупреждение.

Не поддерживаются и останавливают задание с понятной ошибкой, чтобы не потерять данные незаметно:

- proxy-объекты и неизвестные пользовательские объекты;
- внешние ссылки XREF;
- OLE, таблицы CAD, внешние растровые изображения, 3D-тела;
- бесконечные конструкционные линии `XLINE`/`RAY`;
- отсутствующие определения блоков.

Перед выдачей заказчику преобразуйте такие объекты в обычные блоки/геометрию в CAD или настройте экспорт EPLAN без внешних зависимостей.

### PDF

PDF строится через `ezdxf` + `matplotlib` из итогового DWG/DXF. Геометрия, порядок страниц, размер бумаги и область видового экрана сохраняются. **CTB/STB, драйверы печати, точные веса линий CAD и замена SHX-шрифтов не эмулируются.** По умолчанию геометрия чёрная; есть режим цвета слоёв. Для юридически/производственно точной печати нужен отдельный адаптер native-печати AutoCAD/nanoCAD/другого CAD — это следующий этап, а не скрытая возможность текущей версии.

## Быстрый старт Windows

1. Установите Python 3.10+ и ODA File Converter.
2. В корне репозитория запустите:

   ```bat
   scripts\install_windows.bat
   scripts\run_windows.bat
   ```

3. В окне выберите папку с DWG, папку результата и путь к `ODAFileConverter.exe`.
4. Нажмите **«Объединить DWG + PDF»**.

Обычный путь ODA ищется автоматически; также можно задать переменную окружения `NANOMERGER_ODA` или параметр `--oda`.

### Сборка Windows EXE в PyCharm

Самый простой путь — открыть корень репозитория в PyCharm на Windows, открыть
`build_exe.py` и нажать **Run**. Скрипт сам создаст окружение `.venv-build`,
установит зависимости и соберёт приложение:

```text
dist\NanoMerger\NanoMerger.exe
```

Для одного самодостаточного файла задайте параметр запуска `--onefile` или выполните
в терминале PyCharm:

```powershell
python build_exe.py --onefile
# результат: dist\NanoMerger.exe
```

Полезные параметры: `--use-current-env` — использовать текущий venv PyCharm,
`--skip-install` — не устанавливать зависимости, `--console` — сборка с консолью
для диагностики, `--dry-run` — только показать команду. Подробная инструкция и
решение проблем: [`docs/BUILD_EXE.md`](docs/BUILD_EXE.md).

Альтернативный запуск без PyCharm:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1
```

ODA **не упаковывается** внутрь EXE. Соберите и проверьте приложение на целевой
Windows-машине с реальным комплектом EPLAN.

## Linux / macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[gui]"
nanomerger-gui
```

Для Linux может понадобиться системный Qt-рантайм (`libGL`, `libEGL`, `xkbcommon`, `dbus`, xcb). Укажите путь к ODA/AppImage в настройках. Для серверного CLI графический стек не нужен.

## CLI

```bash
# Основной сценарий: DWG -> один DWG + PDF + отчёт
nanomerger merge "C:\EPLAN\Export" -o "C:\EPLAN\Merged" \
  --name "Project_merged" \
  --oda "C:\Program Files\ODA\ODAFileConverter 25.12\ODAFileConverter.exe"

# Одна горизонтальная лента — по умолчанию. Сетка из 4 столбцов:
nanomerger merge ./export -o ./result --columns 4 --gap 50

# Явно задать бумагу и версию DWG
nanomerger merge ./export -o ./result --paper A3 --dwg-version R2018

# Только проверить порядок имён, не читая CAD
nanomerger scan ./export

# Диагностика зависимостей
nanomerger doctor --require-oda

# Машиночитаемый результат для интеграции
nanomerger merge ./export -o ./result --json --quiet
```

На Linux/macOS путь к ODA можно передать через `--oda` или `NANOMERGER_ODA`. Основные параметры:

| Параметр | По умолчанию | Назначение |
|---|---:|---|
| `--gap` | `50` | Зазор между габаритами чертежей в модели, мм |
| `--columns` | `0` | `0` = одна горизонтальная лента; `1+` = число столбцов сетки |
| `--margin` | `10` | Поля нового листа, мм |
| `--paper` | `auto` | `auto`, `source`, `A4`…`A0`; ориентация выбирается по габаритам модели |
| `--dwg-version` | `R2018` | `R2000`, `R2004`, `R2007`, `R2010`, `R2013`, `R2018` |
| `--color-pdf` | выкл. | Цвет слоёв вместо чёрной геометрии |
| `--overwrite` | выкл. | Разрешить замену существующего комплекта |
| `--timeout` | `1800` | Таймаут одного запуска ODA, секунды |

Коды выхода: `0` успех, `2` ошибка входа/параметров, `3` конвертация/зависимость, `4` отмена, `5` результат уже существует, `1` непредвиденная ошибка.

### Демо без ODA и полный DWG-тест

```bash
# Синтетические чертежи: DXF + PDF, ODA не нужен
python examples/make_demo.py

# Тот же демо-комплект через настоящий DWG-конвертер
python examples/make_demo.py --dwg --oda /path/to/ODAFileConverter
```

Демо не является реальным экспортом EPLAN; оно нужно для проверки механики и интерфейса.

## Встраивание в Engi

Репозиторий Engi в этой сессии не подключён, поэтому интеграция сделана через независимый API, без предположений о внутреннем GUI Engi.

### Вариант A: ядро в рабочем потоке Engi

```python
import threading
from nanomerger import MergeOptions, merge_folder

cancel = threading.Event()

def on_progress(event):
    # Вызывается в рабочем потоке. Для GUI Engi передайте событие через сигнал/очередь.
    print(event.stage, event.completed, event.total, event.message)

# Запускайте эту функцию в worker-потоке Engi, не в GUI-потоке:
def run():
    result = merge_folder(
        r"C:\EPLAN\Export",
        r"C:\EPLAN\Merged",
        oda_path=r"C:\Program Files\ODA\ODAFileConverter\ODAFileConverter.exe",
        options=MergeOptions(gap_mm=50, columns=0, paper="auto"),
        progress=on_progress,
        cancel_event=cancel,
    )
    return result.dwg_path, result.pdf_path, result.report_path
```

Упрощённая обёртка: `from nanomerger.engi import merge_for_engi`. Для отмены вызовите `cancel.set()` из другого потока. Ошибки — типизированные исключения `NanoMergerError` с полем `code`.

### Вариант B: отдельное окно внутри Engi

Если Engi использует **PySide6** и уже имеет `QApplication`:

```python
from nanomerger.engi import open_window

nano = open_window(
    input_folder=r"C:\EPLAN\Export",
    oda_path=oda_path,
    parent=engi_main_window,
    on_finished=lambda result: engi_status_bar.showMessage(str(result.pdf_path)),
)
# Храните ссылку nano в Engi, пока окно открыто.
```

Если Engi использует другой GUI-фреймворк, не смешивайте Qt-биндинги: используйте ядро в worker-потоке или запускайте CLI как subprocess с `--json`. Пример: `examples/engi_integration.py`.

## Результаты и отчёт

Для имени `Project_merged` создаются:

```text
Project_merged.dwg          # или .dxf в явном DXF-режиме
Project_merged.pdf
Project_merged.report.json
```

Отчёт содержит версию приложения, параметры, порядок источников, SHA-256 исходников и результатов, габариты в модели, размеры бумаги, имена листов/блоков, масштаб видовых экранов, предупреждения и признак `status: complete`. Временные файлы находятся в служебной папке задания и удаляются после завершения.

## Архитектура

```text
nanomerger/
  discovery.py   # поиск и числовая сортировка
  converters.py  # ODA-адаптер, таймаут, отмена; явный DXF-адаптер
  drawing.py     # габариты, единицы, блоки, сетка модели, листы CAD
  pdf.py         # многостраничный векторный PDF из сохранённого CAD
  publishing.py  # проверка перезаписи, хэши, публикация с откатом
  merger.py      # Qt-free оркестратор для Engi/CLI
  cli.py         # merge / scan / doctor / gui
  gui.py         # PySide6-оболочка, QThread, прогресс и отмена
  engi.py        # маленькая точка интеграции
```

Ядро не импортирует Qt и не меняет глобальный backend matplotlib. GUI-зависимость устанавливается отдельно: `pip install -e ".[gui]"`.

## Проверка

```bash
pip install -e ".[dev]"
ruff check nanomerger tests examples
pytest -q
python -m build --wheel
```

CI настроен для Windows/Linux и Python 3.11/3.12. Автоматические тесты используют DXF и mock/реальные дочерние процессы для проверки контракта конвертера; проприетарный ODA и реальные EPLAN DWG в CI не входят. Обязательная приёмка на реальном комплекте описана в `docs/ACCEPTANCE.md`.

## Лицензии

Код NanoMerger — MIT. ODA File Converter — отдельное проприетарное ПО, устанавливается пользователем. PySide6 — LGPL/commercial, ezdxf — MIT, matplotlib — PSF-based, Pillow — MIT-CMU. Подробности: `THIRD_PARTY_NOTICES.md`.

# Сборка NanoMerger.exe в PyCharm

## Самый простой способ

1. Работайте **на Windows**. PyInstaller не собирает Windows EXE из Linux/macOS.
2. Установите Python **3.11 или 3.12 x64** и выберите его в PyCharm:
   `Settings → Project → Python Interpreter`.
3. Откройте **корень репозитория** как проект.
4. Откройте `build_exe.py`, нажмите ПКМ → **Run 'build_exe'** или зелёный Run.
5. Дождитесь окончания. По умолчанию появится:

   ```text
   dist\NanoMerger\NanoMerger.exe
   ```

Скрипт сам создаёт `.venv-build`, устанавливает GUI-зависимости и PyInstaller,
собирает приложение и кладёт рядом памятку `START_HERE.txt` и лицензии.

## Один файл EXE

В PyCharm: `Run → Edit Configurations… → Parameters`:

```text
--onefile
```

Или в терминале PyCharm:

```powershell
python build_exe.py --onefile
```

Результат:

```text
dist\NanoMerger.exe
```

`--onefile` удобнее пересылать, но он больше и дольше стартует, потому что
распаковывает Qt и библиотеки во временную папку. Для постоянного рабочего места
рекомендуется папочный вариант: распространяйте `dist\NanoMerger` целиком.

## Если зависимости уже установлены в проектном venv

```powershell
python build_exe.py --use-current-env --skip-install
```

Без `--skip-install` скрипт доустановит недостающее в текущий интерпретатор:

```powershell
python build_exe.py --use-current-env
```

## Диагностика

- EXE с консольным выводом: `python build_exe.py --console`.
- Полная пересборка с очисткой кэша выполняется по умолчанию; ускорить повтор
  можно через `--no-clean`.
- Ошибка старта оконного EXE записывается в `%TEMP%\NanoMerger-startup.log` и
  показывается системным диалогом.
- Проверить команду без сборки на любой ОС: `python build_exe.py --dry-run`.

## Что нужно пользователю готового EXE

- Windows и права на запуск приложения.
- **Отдельно установленный ODA File Converter** для DWG. В EXE он не входит.
- Путь к `ODAFileConverter.exe` указывается в окне NanoMerger, через переменную
  `NANOMERGER_ODA` или стандартную установку ODA.
- Для проверки производственного комплекта используйте `docs/ACCEPTANCE.md`.

## Частые проблемы

**PyCharm запускает не тот Python.** Проверьте интерпретатор в Run Configuration;
скрипт требует Python 3.10–3.13. Рекомендуется 3.11/3.12 x64.

**Антивирус блокирует один EXE.** Используйте папочную сборку без `--onefile`,
не включайте UPX (скрипт передаёт `--noupx`) и подписывайте распространяемый EXE
корпоративным сертификатом, если это требуется политикой заказчика.

**Не найден Qt platform plugin.** Запустите обычную пересборку без `--no-clean`:
по умолчанию выполняется `--clean`. Не удаляйте папку `_internal` рядом с EXE в
папочной сборке.

**DWG не открывается.** Это не ошибка PyInstaller: установите ODA и проверьте
путь. PDF в текущей версии — векторный предпросмотр геометрии, не точная печать
CAD с CTB/STB.

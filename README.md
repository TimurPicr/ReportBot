# ReportBot

Полностью локальный MVP для извлечения фактов из свободного русского текста, хранения в SQLite, генерации технических отчётов через Ollama, автоматического удаления неподтверждённых утверждений и экспорта DOCX.

## Архитектура

```text
app.py                         точка запуска Streamlit
report_system/domain.py        модели, enums, provenance и validation result
report_system/llm.py           Ollama/Fake, extraction, generation и semantic validation
report_system/storage.py       SQLAlchemy, SQLite repository и зависимости
report_system/application.py   workflow и deterministic build_test_act()
report_system/validation.py    проверка чисел, дат и идентификаторов
report_system/docx.py          загрузка шаблона и DOCX export
report_system/ui.py            тонкий Streamlit UI
report_system/config.py        локальная конфигурация
prompts/                       редактируемые LLM-инструкции
templates/                     редактируемые DOCX-шаблоны
tests/                         четыре тестовых модуля без Ollama
my_tests/                      notebook и файлы ручного тестирования
```

Рекомендуемый порядок чтения: `domain.py` → `llm.py` и `storage.py` → `application.py` → `ui.py`.
Классами оставлены только модели данных, два LLM provider, SQLite repository, настройки и единый
`ReportApplication`. Загрузчики prompts/templates, validators и `build_test_act()` реализованы
обычными функциями.

Временные ряды больше 1000 точек нельзя хранить inline: используйте `file`/`image_reference` или внешний локальный файл. Неизвестные имена параметров разрешены. Содержимое документов хранится JSON, связи нормализованы отдельно и содержат revision источника.

## Установка с нуля

Требуются Python 3.11+ и локальный Ollama.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
ollama pull qwen3.5:9b
ollama serve
```

В другом терминале:

```bash
source .venv/bin/activate
streamlit run app.py
```

Ollama URL намеренно разрешён только на loopback (`127.0.0.1`, `localhost`, `::1`), proxy-переменные игнорируются. Streamlit слушает только `127.0.0.1`, telemetry отключена в `.streamlit/config.toml`. Внешние LLM API и облачные хранилища не используются.

## Workflow

1. Выберите `manufacturing_act` или `test_protocol`, введите текст и нажмите «Сформировать документ».
2. Структурированные данные автоматически проверяются Pydantic и сохраняются без ручного JSON-review.
3. Сгенерированный текст проверяется детерминированным и смысловым валидаторами. При обнаружении неподтверждённых утверждений Ollama удаляет их, после чего текст проверяется повторно.
4. Текст сохраняется и DOCX становится доступен только после успешной повторной проверки. Невалидный текст не сохраняется и не показывается пользователю.
5. Во вкладке «Акт испытаний» выберите подтверждённые протоколы. Структуру и provenance агрегирует Python, LLM оформляет текст.

## Проверки и demo

```bash
pytest
python demo.py
```

`demo.py` использует `FakeLLMProvider`, не требует Ollama и создаёт `data/generated/*.docx`.

## Шаблоны

В проекте находятся редактируемые `templates/manufacturing_act.docx`, `templates/test_protocol.docx`, `templates/test_act.docx`. Поддерживаются placeholders `{{title}}`, `{{document_id}}`, `{{generated_text}}`; без файла создаётся минимальный DOCX.

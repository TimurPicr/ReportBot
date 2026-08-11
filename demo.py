"""Offline demo using FakeLLMProvider; no Ollama process is required."""

from pathlib import Path

from report_system.application import ReportApplication
from report_system.config import Settings
from report_system.domain import DocumentType
from report_system.llm import FakeLLMProvider


ROOT = Path(__file__).parent
RAW = (
    "После прокатки электрод сушили в вакуумной печи в течение 12 часов при температуре "
    "120 °C и давлении 0.01 мбар. После сушки был получен образец E-17."
)


def main() -> None:
    extracted = {
        "title": "Акт наработки образца E-17",
        "sections": [
            {
                "name": "Технологический процесс",
                "records": [
                    {
                        "type": "process",
                        "name": "Вакуумная сушка",
                        "parameters": [
                            {"key": "duration", "name": "Продолжительность", "value": 12, "unit": "ч", "source": {"source_type": "user_input", "raw_text_fragment": "в течение 12 часов"}},
                            {"key": "temperature", "name": "Температура", "value": 120, "unit": "°C", "source": {"source_type": "user_input", "raw_text_fragment": "120 °C"}},
                            {"key": "pressure", "name": "Давление", "value": 0.01, "unit": "мбар", "source": {"source_type": "user_input", "raw_text_fragment": "0.01 мбар"}},
                            {"key": "sample_id", "name": "Образец", "value": "E-17", "value_type": "text", "source": {"source_type": "user_input", "raw_text_fragment": "образец E-17"}},
                        ],
                    }
                ],
            }
        ],
    }
    generated = (
        "После прокатки электрод подвергнут вакуумной сушке в течение 12 ч при температуре "
        "120 °C и давлении 0.01 мбар. По завершении получен образец E-17."
    )
    provider = FakeLLMProvider([extracted, generated, {"valid": True, "issues": []}])
    application = ReportApplication(
        Settings(
            database_url=f"sqlite:///{ROOT / 'data' / 'demo.db'}",
            prompts_dir=ROOT / "prompts",
            templates_dir=ROOT / "templates",
            examples_dir=ROOT / "examples",
            output_dir=ROOT / "data" / "generated",
        ),
        provider,
    )
    document = application.confirm(application.extract(DocumentType.MANUFACTURING_ACT, RAW))
    document, validation, output = application.generate(document.id)
    print(document.model_dump_json(indent=2))
    print(f"Valid: {validation.valid}; DOCX: {output}")


if __name__ == "__main__":
    main()

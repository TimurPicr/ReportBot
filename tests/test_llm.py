from pathlib import Path
from typing import Any

import httpx
import pytest

from report_system.domain import Document, DocumentStatus, DocumentType, ValidationResult
from report_system.llm import (
    FakeLLMProvider,
    OllamaProvider,
    extract_document,
    generate_report,
    revise_report,
    validate_semantics,
)


ROOT = Path(__file__).parents[1]


def test_extraction_uses_schema_and_preserves_only_returned_facts() -> None:
    provider = FakeLLMProvider(
        [
            {
                "title": "Акт E-17",
                "sections": [
                    {
                        "name": "Процесс",
                        "records": [
                            {
                                "type": "process",
                                "name": "Сушка",
                                "parameters": [
                                    {
                                        "name": "Образец",
                                        "value": "E-17",
                                        "source": {
                                            "source_type": "user_input",
                                            "raw_text_fragment": "образец E-17",
                                        },
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ]
    )
    document = extract_document(
        provider,
        ROOT / "prompts",
        DocumentType.MANUFACTURING_ACT,
        "Сушили образец E-17.",
    )
    assert document.status == DocumentStatus.EXTRACTED
    assert document.sections[0].name == "Процесс"
    schema = provider.requests[0]["json_schema"]
    assert schema is not None
    parameter_schema = schema["$defs"]["Parameter"]
    assert "source" in parameter_schema["required"]
    assert "key" not in parameter_schema["properties"]
    assert "description" not in schema["$defs"]["Record"]["properties"]
    assert "description" not in schema["$defs"]["Section"]["properties"]
    assert schema["$defs"]["SourceReference"]["required"] == ["source_type", "raw_text_fragment"]
    assert "pressure" not in document.model_dump_json()


def test_extraction_rejects_non_verbatim_source() -> None:
    provider = FakeLLMProvider(
        [
            {
                "sections": [
                    {
                        "name": "Процесс",
                        "records": [
                            {
                                "type": "process",
                                "name": "Сушка",
                                "parameters": [
                                    {
                                        "name": "Температура",
                                        "value": 120,
                                        "source": {
                                            "source_type": "user_input",
                                            "raw_text_fragment": "температура 120 °C",
                                        },
                                    }
                                ],
                            }
                        ],
                    }
                ]
            }
        ]
    )
    with pytest.raises(ValueError, match="not an exact fragment"):
        extract_document(provider, ROOT / "prompts", DocumentType.MANUFACTURING_ACT, "Сушили при 120 °C.")


def test_extraction_rejects_unsupported_type_and_blank_text() -> None:
    provider = FakeLLMProvider([])
    with pytest.raises(ValueError, match="not supported"):
        extract_document(provider, ROOT / "prompts", DocumentType.TEST_ACT, "данные")
    with pytest.raises(ValueError, match="cannot be empty"):
        extract_document(provider, ROOT / "prompts", DocumentType.TEST_PROTOCOL, "  ")


def test_generation_requires_confirmation() -> None:
    provider = FakeLLMProvider(["  Технический текст.  "])
    document = Document(document_type=DocumentType.TEST_PROTOCOL)
    with pytest.raises(ValueError, match="confirmed"):
        generate_report(provider, ROOT / "prompts", document)
    document.status = DocumentStatus.CONFIRMED
    assert generate_report(provider, ROOT / "prompts", document) == "Технический текст."
    assert "ПРИМЕРЫ СТИЛЯ" not in provider.requests[-1]["prompt"]


def test_semantic_validation_is_structured() -> None:
    provider = FakeLLMProvider([{"valid": False, "issues": [{"severity": "error", "statement": "печь", "reason": "не задана"}]}])
    result = validate_semantics(
        provider,
        ROOT / "prompts",
        Document(document_type=DocumentType.TEST_PROTOCOL),
        "Испытание в печи",
    )
    assert isinstance(result, ValidationResult)
    assert not result.valid


def test_report_revision_receives_confirmed_facts_and_issues() -> None:
    provider = FakeLLMProvider(["Исправленный текст."])
    document = Document(
        document_type=DocumentType.TEST_PROTOCOL,
        title="Протокол P-001",
    )
    validation = ValidationResult.model_validate(
        {
            "valid": False,
            "issues": [
                {
                    "severity": "error",
                    "statement": "999",
                    "reason": "Число не подтверждено",
                }
            ],
        }
    )
    result = revise_report(provider, ROOT / "prompts", document, "Значение 999.", validation)
    assert result == "Исправленный текст."
    request = provider.requests[0]["prompt"]
    assert "Протокол P-001" in request
    assert "Значение 999." in request
    assert "Число не подтверждено" in request
    assert provider.requests[0]["temperature"] == 0.0


def test_ollama_is_loopback_only_and_disables_thinking(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError, match="loopback"):
        OllamaProvider("http://localhost.example:11434", "model")
    captured: dict[str, Any] = {}

    def fake_post(client: httpx.Client, url: str, *, json: dict[str, Any]) -> httpx.Response:
        captured.update(json)
        return httpx.Response(200, json={"response": '{"ok": true}'}, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    result = OllamaProvider("http://127.0.0.1:11434", "qwen3.5:9b").generate(
        "prompt", json_schema={"type": "object"}
    )
    assert result == {"ok": True}
    assert captured["think"] is False

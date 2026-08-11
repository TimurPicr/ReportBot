from pathlib import Path

import pytest
from docx import Document as DocxDocument

from report_system.application import ReportApplication, build_test_act
from report_system.config import Settings
from report_system.docx import generate_docx
from report_system.domain import (
    Document,
    DocumentStatus,
    DocumentType,
    Parameter,
    Record,
    Section,
)
from report_system.llm import FakeLLMProvider, load_examples
from report_system.validation import validate_facts


ROOT = Path(__file__).parents[1]


def settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'app.db'}",
        output_dir=tmp_path / "output",
        prompts_dir=ROOT / "prompts",
        templates_dir=ROOT / "templates",
        examples_dir=ROOT / "examples",
    )


def protocol(identifier: str, capacity: float, deviation: bool = False) -> Document:
    records = [Record(type="measurement", name="Ёмкость", parameters=[Parameter(name="Значение", value=capacity, unit="А·ч")])]
    if deviation:
        records.append(Record(type="deviation", name="Отклонение", parameters=[]))
    return Document(
        id=identifier,
        document_type=DocumentType.TEST_PROTOCOL,
        title=f"Протокол {identifier}",
        status=DocumentStatus.CONFIRMED,
        sections=[Section(name="Результаты", records=records)],
        conclusion="Испытание завершено",
    )


def test_deterministic_validation_detects_unknown_facts() -> None:
    document = Document(
        document_type=DocumentType.MANUFACTURING_ACT,
        title="Акт E-17",
        sections=[Section(name="Процесс", records=[Record(type="process", name="Сушка", parameters=[Parameter(name="Температура", value=120)])])],
    )
    valid = validate_facts(document, "Образец E-17 сушили при 120 °C.")
    invalid = validate_facts(document, "Образец X-99 сушили при 130 °C.")
    assert valid.valid
    assert {issue.check for issue in invalid.issues} == {"unknown_number", "unknown_identifier"}


def test_test_act_is_built_deterministically_with_provenance() -> None:
    act = build_test_act([protocol("P-001", 4.81), protocol("P-002", 4.77, True)])
    counts = {item.key: item.value for item in act.sections[1].records[0].parameters}
    assert counts == {"protocol_count": 2, "test_count": 2, "result_count": 2, "deviation_count": 1}
    results = next(section for section in act.sections if section.name == "Результаты испытаний")
    assert results.records[0].parameters[0].source.source_id == "P-001"  # type: ignore[union-attr]


def test_test_act_rejects_wrong_or_unconfirmed_input() -> None:
    draft = protocol("P-001", 4.81)
    draft.status = DocumentStatus.EXTRACTED
    with pytest.raises(ValueError, match="confirmed"):
        build_test_act([draft])
    with pytest.raises(ValueError, match="not a test protocol"):
        build_test_act([Document(document_type=DocumentType.MANUFACTURING_ACT, status=DocumentStatus.CONFIRMED)])


def test_complete_review_generation_and_docx_flow(tmp_path: Path) -> None:
    provider = FakeLLMProvider(
        [
            {"title": "Акт E-17", "sections": []},
            "Получен образец E-17.",
            {"valid": True, "issues": []},
        ]
    )
    application = ReportApplication(settings(tmp_path), provider)
    extracted = application.extract(DocumentType.MANUFACTURING_ACT, "Получен образец E-17.")
    assert application.repository.get(extracted.id) is None
    confirmed = application.confirm(extracted)
    document, validation, output = application.generate(confirmed.id)
    assert document.status == DocumentStatus.GENERATED
    assert validation.valid and output and output.exists()
    assert application.repository.get(document.id).revision == 1  # type: ignore[union-attr]


def test_invalid_report_is_not_exported(tmp_path: Path) -> None:
    application = ReportApplication(settings(tmp_path), FakeLLMProvider(["Добавлено значение 999."]))
    source = application.confirm(Document(document_type=DocumentType.TEST_PROTOCOL))
    document, validation, output = application.generate(source.id, semantic_validation=False)
    assert not validation.valid
    assert output is None
    assert document.status == DocumentStatus.CONFIRMED


def test_editable_assets_and_real_template_are_usable(tmp_path: Path) -> None:
    for name in ("manufacturing_act.docx", "test_protocol.docx", "test_act.docx"):
        text = "\n".join(paragraph.text for paragraph in DocxDocument(ROOT / "templates" / name).paragraphs)
        assert "{{title}}" in text and "{{document_id}}" in text
    for document_type in DocumentType:
        examples = load_examples(ROOT / "examples", document_type)
        assert len(examples) == 2
        assert all("УЧЕБНЫЙ ПРИМЕР" in example for example in examples)

    document = Document(
        id="MA-CHECK-001",
        document_type=DocumentType.MANUFACTURING_ACT,
        title="Проверочный акт",
        status=DocumentStatus.GENERATED,
        generated_text="Проверочный текст.",
    )
    output = generate_docx(document, ROOT / "templates", tmp_path)
    paragraphs = [paragraph.text for paragraph in DocxDocument(output).paragraphs]
    assert paragraphs.count("Проверочный акт") == 1
    assert "Идентификатор документа: MA-CHECK-001" in paragraphs

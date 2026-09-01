import pytest
from pydantic import ValidationError

from report_system.domain import (
    Document,
    DocumentReference,
    DocumentType,
    Parameter,
    Record,
    RelationType,
    Section,
    SourceReference,
    ValueType,
)


def test_unknown_parameter_and_provenance_are_supported() -> None:
    parameter = Parameter(
        name="Степень набухания сепаратора",
        value=17.2,
        unit="%",
        source=SourceReference(source_type="user_input", raw_text_fragment="17.2 %"),
    )
    assert "key" not in Parameter.model_fields
    assert parameter.source.raw_text_fragment == "17.2 %"


def test_parameter_requires_source_and_descriptions_are_not_supported() -> None:
    with pytest.raises(ValidationError, match="source"):
        Parameter(name="Температура", value=120)
    assert "description" not in Record.model_fields
    assert "description" not in Section.model_fields


def test_document_has_isolated_mutable_defaults_and_flexible_records() -> None:
    first = Section(name="Первый")
    second = Section(name="Второй")
    first.records.append(Record(type="process", name="Сушка"))
    document = Document(document_type=DocumentType.MANUFACTURING_ACT, sections=[first])
    assert second.records == []
    assert document.sections[0].records[0].name == "Сушка"


def test_large_inline_timeseries_is_rejected() -> None:
    with pytest.raises(ValidationError, match="stored externally"):
        Parameter(
            name="Сигнал",
            value=list(range(1001)),
            value_type=ValueType.TIMESERIES,
            source=SourceReference(source_type="file", source_path="signal.csv"),
        )


def test_document_reference_tracks_revision_and_rejects_self_reference() -> None:
    reference = DocumentReference(
        source_id="P-001",
        target_id="A-001",
        relation_type=RelationType.BASED_ON_PROTOCOL,
        source_revision=2,
    )
    assert reference.source_revision == 2
    with pytest.raises(ValidationError, match="cannot reference itself"):
        DocumentReference(source_id="same", target_id="same", relation_type=RelationType.SUMMARIZES)

from copy import deepcopy
from pathlib import Path

import pytest

from report_system.domain import (
    Document,
    DocumentReference,
    DocumentType,
    Parameter,
    Record,
    RelationType,
    Section,
    SourceReference,
)
from report_system.storage import DocumentRepository, DocumentRow


@pytest.fixture
def repository(tmp_path: Path) -> DocumentRepository:
    return DocumentRepository(f"sqlite:///{tmp_path / 'test.db'}")


def test_crud_and_revision_conflict(repository: DocumentRepository) -> None:
    document = Document(document_type=DocumentType.TEST_PROTOCOL, title="P-001")
    repository.create(document)
    stale_copy = document.model_copy(deep=True)
    document.sections.append(Section(name="Результаты"))
    repository.update(document)
    assert repository.get(document.id).revision == 2  # type: ignore[union-attr]
    with pytest.raises(ValueError, match="revision conflict"):
        repository.update(stale_copy)
    assert len(repository.list(DocumentType.TEST_PROTOCOL.value)) == 1
    assert repository.delete(document.id)


def test_dependency_becomes_stale_after_source_update(repository: DocumentRepository) -> None:
    protocol = Document(document_type=DocumentType.TEST_PROTOCOL)
    act = Document(document_type=DocumentType.TEST_ACT, source_document_ids=[protocol.id])
    repository.create(protocol)
    repository.create(act)
    reference = repository.add_reference(
        DocumentReference(source_id=protocol.id, target_id=act.id, relation_type=RelationType.BASED_ON_PROTOCOL)
    )
    assert reference.source_revision == 1
    assert not repository.is_stale(act.id)
    protocol.title = "Исправлен"
    repository.update(protocol)
    assert repository.is_stale(act.id)


def test_reference_requires_existing_documents(repository: DocumentRepository) -> None:
    with pytest.raises(KeyError, match="must exist"):
        repository.add_reference(
            DocumentReference(source_id="missing", target_id="also-missing", relation_type=RelationType.SUMMARIZES)
        )


def test_legacy_document_is_normalized_when_loaded(repository: DocumentRepository) -> None:
    document = Document(
        document_type=DocumentType.MANUFACTURING_ACT,
        sections=[
            Section(
                name="Процесс",
                records=[
                    Record(
                        type="measurement",
                        name="Температура",
                        parameters=[
                            Parameter(
                                name="Значение",
                                value=120,
                                source=SourceReference(
                                    source_type="user_input",
                                    raw_text_fragment="120 °C",
                                ),
                            )
                        ],
                    )
                ],
            )
        ],
    )
    repository.create(document)
    with repository.sessions.begin() as session:
        row = session.get(DocumentRow, document.id)
        assert row is not None
        content = deepcopy(row.content)
        section = content["sections"][0]
        section["description"] = "Старое описание раздела"
        record = section["records"][0]
        record["description"] = None
        parameter = record["parameters"][0]
        parameter["key"] = "temperature"
        parameter["source"] = None
        row.content = content

    loaded = next(item for item in repository.list() if item.id == document.id)
    parameter = loaded.sections[0].records[0].parameters[0]
    assert parameter.source.source_type == "legacy_document"
    assert parameter.source.source_id == document.id
    assert "key" not in parameter.model_dump()
    assert "description" not in loaded.sections[0].model_dump()
    assert "description" not in loaded.sections[0].records[0].model_dump()

    with repository.sessions() as session:
        stored = session.get(DocumentRow, document.id)
        assert stored is not None
        assert stored.content["sections"][0]["description"] == "Старое описание раздела"

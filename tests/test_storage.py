from pathlib import Path

import pytest

from report_system.domain import Document, DocumentReference, DocumentType, RelationType, Section
from report_system.storage import DocumentRepository


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


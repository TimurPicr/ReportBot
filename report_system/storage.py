from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, create_engine, event, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from report_system.domain import Document, DocumentReference


class Base(DeclarativeBase):
    pass


class DocumentRow(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    document_type: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(32), index=True)
    raw_input: Mapped[str | None] = mapped_column(Text)
    content: Mapped[dict[str, Any]] = mapped_column("structured_content", JSON)
    generated_text: Mapped[str | None] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    docx_path: Mapped[str | None] = mapped_column(Text)


class ReferenceRow(Base):
    __tablename__ = "document_references"
    __table_args__ = (UniqueConstraint("source_id", "target_id", "relation_type"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    target_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    relation_type: Mapped[str] = mapped_column(String(64))
    source_revision: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DocumentRepository:
    def __init__(self, database_url: str) -> None:
        if database_url.startswith("sqlite:///"):
            path = Path(database_url.removeprefix("sqlite:///"))
            if str(path) != ":memory:":
                path.parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(database_url)
        if database_url.startswith("sqlite"):
            @event.listens_for(engine, "connect")
            def enable_foreign_keys(connection: object, _record: object) -> None:
                cursor = connection.cursor()  # type: ignore[attr-defined]
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()
        Base.metadata.create_all(engine)
        self.sessions = sessionmaker(engine, expire_on_commit=False)

    def create(self, document: Document, docx_path: str | None = None) -> Document:
        with self.sessions.begin() as session:
            if session.get(DocumentRow, document.id):
                raise ValueError(f"document {document.id} already exists")
            session.add(self._row(document, docx_path))
        return document

    def get(self, document_id: str) -> Document | None:
        with self.sessions() as session:
            row = session.get(DocumentRow, document_id)
            return Document.model_validate(row.content) if row else None

    def list(self, document_type: str | None = None) -> list[Document]:
        query = select(DocumentRow).order_by(DocumentRow.created_at.desc())
        if document_type:
            query = query.where(DocumentRow.document_type == document_type)
        with self.sessions() as session:
            return [Document.model_validate(row.content) for row in session.scalars(query)]

    def update(
        self,
        document: Document,
        docx_path: str | None = None,
        *,
        increment_revision: bool = True,
    ) -> Document:
        with self.sessions.begin() as session:
            row = session.get(DocumentRow, document.id)
            if row is None:
                raise KeyError(document.id)
            if document.revision != row.revision:
                raise ValueError(f"revision conflict for {document.id}: expected {row.revision}, got {document.revision}")
            document.revision = row.revision + 1 if increment_revision else row.revision
            document.updated_at = datetime.now(UTC)
            row.document_type = document.document_type.value
            row.title = document.title
            row.status = document.status.value
            row.raw_input = document.raw_input
            row.content = document.model_dump(mode="json")
            row.generated_text = document.generated_text
            row.revision = document.revision
            row.updated_at = document.updated_at
            if docx_path is not None:
                row.docx_path = docx_path
        return document

    def delete(self, document_id: str) -> bool:
        with self.sessions.begin() as session:
            row = session.get(DocumentRow, document_id)
            if row is None:
                return False
            session.delete(row)
            return True

    def add_reference(self, reference: DocumentReference) -> DocumentReference:
        with self.sessions.begin() as session:
            source = session.get(DocumentRow, reference.source_id)
            target = session.get(DocumentRow, reference.target_id)
            if source is None or target is None:
                raise KeyError("both referenced documents must exist")
            reference.source_revision = reference.source_revision or source.revision
            session.add(
                ReferenceRow(
                    source_id=reference.source_id,
                    target_id=reference.target_id,
                    relation_type=reference.relation_type.value,
                    source_revision=reference.source_revision,
                    created_at=reference.created_at,
                )
            )
        return reference

    def is_stale(self, document_id: str) -> bool:
        query = (
            select(ReferenceRow, DocumentRow)
            .join(DocumentRow, DocumentRow.id == ReferenceRow.source_id)
            .where(ReferenceRow.target_id == document_id)
        )
        with self.sessions() as session:
            return any(reference.source_revision != source.revision for reference, source in session.execute(query))

    @staticmethod
    def _row(document: Document, docx_path: str | None) -> DocumentRow:
        return DocumentRow(
            id=document.id,
            document_type=document.document_type.value,
            title=document.title,
            status=document.status.value,
            raw_input=document.raw_input,
            content=document.model_dump(mode="json"),
            generated_text=document.generated_text,
            revision=document.revision,
            created_at=document.created_at,
            updated_at=document.updated_at,
            docx_path=docx_path,
        )


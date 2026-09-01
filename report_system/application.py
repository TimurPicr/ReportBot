from pathlib import Path

from report_system.config import Settings
from report_system.docx import generate_docx
from report_system.domain import (
    Document,
    DocumentReference,
    DocumentStatus,
    DocumentType,
    Parameter,
    Record,
    RelationType,
    Section,
    SourceReference,
    ValidationResult,
    ValueType,
)
from report_system.llm import (
    LLMProvider,
    OllamaProvider,
    extract_document,
    generate_report,
    revise_report,
    validate_semantics,
)
from report_system.storage import DocumentRepository
from report_system.validation import validate_facts


class ReportApplication:
    """The complete use-case layer used by Streamlit and tests."""

    def __init__(self, settings: Settings, provider: LLMProvider | None = None) -> None:
        self.settings = settings
        self.provider = provider or OllamaProvider(settings.ollama_url, settings.ollama_model)
        self.repository = DocumentRepository(settings.database_url)

    def extract(self, document_type: DocumentType, raw_input: str) -> Document:
        return extract_document(self.provider, self.settings.prompts_dir, document_type, raw_input)

    def confirm(self, document: Document) -> Document:
        if document.status not in {DocumentStatus.DRAFT, DocumentStatus.EXTRACTED, DocumentStatus.CONFIRMED}:
            raise ValueError("only reviewed structured data can be confirmed")
        document.status = DocumentStatus.CONFIRMED
        return self.repository.update(document) if self.repository.get(document.id) else self.repository.create(document)

    def generate(
        self,
        document_id: str,
        *,
        semantic_validation: bool = True,
    ) -> tuple[Document, ValidationResult, Path | None]:
        document = self.repository.get(document_id)
        if document is None:
            raise KeyError(document_id)
        document.generated_text = None
        text = generate_report(
            self.provider,
            self.settings.prompts_dir,
            document,
        )
        validation = self._validate_generated_text(document, text, semantic_validation)
        if not validation.valid:
            text = revise_report(
                self.provider,
                self.settings.prompts_dir,
                document,
                text,
                validation,
            )
            validation = self._validate_generated_text(document, text, semantic_validation)

        if not validation.valid:
            document.status = DocumentStatus.CONFIRMED
            self.repository.update(document, increment_revision=False)
            return document, validation, None

        document.generated_text = text
        document.status = DocumentStatus.GENERATED
        output = generate_docx(document, self.settings.templates_dir, self.settings.output_dir)
        self.repository.update(document, str(output), increment_revision=False)
        return document, validation, output

    def _validate_generated_text(
        self,
        document: Document,
        text: str,
        semantic_validation: bool,
    ) -> ValidationResult:
        deterministic = validate_facts(document, text)
        if not semantic_validation:
            return deterministic
        semantic = validate_semantics(self.provider, self.settings.prompts_dir, document, text)
        issues = deterministic.issues + semantic.issues
        return ValidationResult(
            valid=deterministic.valid and semantic.valid and not issues,
            issues=issues,
        )

    def build_test_act(self, protocol_ids: list[str], title: str | None = None) -> Document:
        protocols: list[Document] = []
        for protocol_id in protocol_ids:
            protocol = self.repository.get(protocol_id)
            if protocol is None:
                raise KeyError(protocol_id)
            protocols.append(protocol)
        act = build_test_act(protocols, title)
        self.repository.create(act)
        for protocol in protocols:
            self.repository.add_reference(
                DocumentReference(
                    source_id=protocol.id,
                    target_id=act.id,
                    relation_type=RelationType.BASED_ON_PROTOCOL,
                    source_revision=protocol.revision,
                )
            )
        return act


def build_test_act(protocols: list[Document], title: str | None = None) -> Document:
    if not protocols:
        raise ValueError("at least one protocol is required")
    if len(protocols) != len({protocol.id for protocol in protocols}):
        raise ValueError("protocols must be unique")
    for protocol in protocols:
        if protocol.document_type != DocumentType.TEST_PROTOCOL:
            raise ValueError(f"document {protocol.id} is not a test protocol")
        if protocol.status not in {DocumentStatus.CONFIRMED, DocumentStatus.GENERATED}:
            raise ValueError(f"protocol {protocol.id} must be confirmed")

    results: list[Record] = []
    deviations: list[Record] = []
    conclusions: list[Record] = []
    test_count = 0
    for protocol in protocols:
        for section in protocol.sections:
            for record in section.records:
                record_type = record.type.lower()
                test_count += record_type in {"test", "procedure", "measurement"}
                copied = record.model_copy(deep=True)
                for parameter in copied.parameters:
                    parameter.source = SourceReference(source_type="test_protocol", source_id=protocol.id)
                if record_type in {"measurement", "result"}:
                    results.append(copied)
                if record_type == "deviation" or "отклон" in record.name.lower():
                    deviations.append(copied)
        if protocol.conclusion:
            conclusions.append(
                Record(
                    type="source_conclusion",
                    name=protocol.title or protocol.id,
                    parameters=[
                        Parameter(
                            key="conclusion",
                            name="Заключение протокола",
                            value=protocol.conclusion,
                            value_type=ValueType.TEXT,
                            source=SourceReference(source_type="test_protocol", source_id=protocol.id),
                        )
                    ],
                )
            )

    references = [
        Record(
            type="protocol_reference",
            name=protocol.title or protocol.id,
            parameters=[
                Parameter(
                    key="protocol_id",
                    name="Идентификатор протокола",
                    value=protocol.id,
                    value_type=ValueType.TEXT,
                    source=SourceReference(source_type="test_protocol", source_id=protocol.id),
                )
            ],
        )
        for protocol in protocols
    ]
    summary = Record(
        type="aggregation_summary",
        name="Сводные показатели",
        parameters=[
            Parameter(key="protocol_count", name="Количество протоколов", value=len(protocols)),
            Parameter(key="test_count", name="Количество испытаний", value=test_count),
            Parameter(key="result_count", name="Количество результатов", value=len(results)),
            Parameter(key="deviation_count", name="Количество отклонений", value=len(deviations)),
        ],
    )
    sections = [
        Section(name="Использованные протоколы", records=references),
        Section(name="Сводка", records=[summary]),
    ]
    for name, records in (
        ("Результаты испытаний", results),
        ("Отклонения", deviations),
        ("Заключения протоколов", conclusions),
    ):
        if records:
            sections.append(Section(name=name, records=records))
    return Document(
        document_type=DocumentType.TEST_ACT,
        title=title or "Акт испытаний",
        sections=sections,
        source_document_ids=[protocol.id for protocol in protocols],
        status=DocumentStatus.CONFIRMED,
        metadata={"aggregation": "deterministic", "protocol_count": len(protocols)},
    )

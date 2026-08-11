from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DocumentType(StrEnum):
    MANUFACTURING_ACT = "manufacturing_act"
    TEST_PROTOCOL = "test_protocol"
    TEST_ACT = "test_act"


class DocumentStatus(StrEnum):
    DRAFT = "draft"
    EXTRACTED = "extracted"
    CONFIRMED = "confirmed"
    GENERATED = "generated"


class ValueType(StrEnum):
    SCALAR = "scalar"
    TEXT = "text"
    BOOLEAN = "boolean"
    TABLE = "table"
    TIMESERIES = "timeseries"
    FILE = "file"
    IMAGE_REFERENCE = "image_reference"
    LIST = "list"


class RelationType(StrEnum):
    PRODUCED_SAMPLE = "produced_sample"
    TESTS_SAMPLE = "tests_sample"
    BASED_ON_PROTOCOL = "based_on_protocol"
    SUMMARIZES = "summarizes"


class SourceReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_type: str = Field(min_length=1)
    source_id: str | None = None
    raw_text_fragment: str | None = None
    source_path: str | None = None

    @model_validator(mode="after")
    def require_locator(self) -> "SourceReference":
        if not any((self.source_id, self.raw_text_fragment, self.source_path)):
            raise ValueError("source must contain an id, text fragment, or path")
        return self


class DocumentReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    relation_type: RelationType
    source_revision: int | None = Field(default=None, ge=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def reject_self_reference(self) -> "DocumentReference":
        if self.source_id == self.target_id:
            raise ValueError("document cannot reference itself")
        return self


class Parameter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str | None = None
    name: str = Field(min_length=1)
    value: Any
    unit: str | None = None
    value_type: ValueType = ValueType.SCALAR
    source: SourceReference | None = None

    @model_validator(mode="after")
    def validate_value_shape(self) -> "Parameter":
        expected: dict[ValueType, type | tuple[type, ...]] = {
            ValueType.TEXT: str,
            ValueType.BOOLEAN: bool,
            ValueType.TABLE: (list, dict),
            ValueType.LIST: list,
            ValueType.FILE: (str, dict),
            ValueType.IMAGE_REFERENCE: (str, dict),
        }
        required_type = expected.get(self.value_type)
        if required_type is not None and not isinstance(self.value, required_type):
            raise ValueError(f"value does not match value_type={self.value_type}")
        if self.value_type == ValueType.TIMESERIES and isinstance(self.value, list) and len(self.value) > 1_000:
            raise ValueError("large timeseries must be stored externally and referenced")
        return self


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str | None = None
    parameters: list[Parameter] = Field(default_factory=list)


class Section(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    description: str | None = None
    records: list[Record] = Field(default_factory=list)


class Document(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    id: str = Field(default_factory=lambda: str(uuid4()))
    document_type: DocumentType
    title: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    sections: list[Section] = Field(default_factory=list)
    source_document_ids: list[str] = Field(default_factory=list)
    raw_input: str | None = None
    conclusion: str | None = None
    generated_text: str | None = None
    status: DocumentStatus = DocumentStatus.DRAFT
    revision: int = Field(default=1, ge=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def validate_sources(self) -> "Document":
        if self.id in self.source_document_ids:
            raise ValueError("document cannot be its own source")
        if len(self.source_document_ids) != len(set(self.source_document_ids)):
            raise ValueError("source_document_ids must be unique")
        return self


class ValidationIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    severity: Literal["error", "warning"]
    statement: str
    reason: str
    check: str | None = None


class ValidationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    valid: bool
    issues: list[ValidationIssue] = Field(default_factory=list)


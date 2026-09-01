import re
from decimal import Decimal, InvalidOperation
from typing import Any

from report_system.domain import Document, ValidationIssue, ValidationResult


NUMBER = re.compile(r"(?<![\w-])[+-]?(?:\d{1,3}(?:[ \u00a0]\d{3})+|\d+)(?:[.,]\d+)?(?![\w-])")
IDENTIFIER = re.compile(r"(?<!\w)[A-Za-zА-Яа-яЁё]{1,12}-\d{1,12}(?!\w)")
DATE = re.compile(r"(?<!\d)(?:0?[1-9]|[12]\d|3[01])[./-](?:0?[1-9]|1[0-2])[./-](?:19|20)\d{2}(?!\d)")


def validate_facts(document: Document, text: str) -> ValidationResult:
    facts: Any = {
        "title": document.title,
        "metadata": document.metadata,
        "sections": [section.model_dump(mode="json") for section in document.sections],
        "source_document_ids": document.source_document_ids,
        "conclusion": document.conclusion,
    }
    source_text = list(_text_values(facts))
    numbers = {_number(token) for value in source_text for token in NUMBER.findall(value)}
    identifiers = {token for value in source_text for token in IDENTIFIER.findall(value)}
    dates = {token for value in source_text for token in DATE.findall(value)}
    issues: list[ValidationIssue] = []

    for token in dict.fromkeys(_report_numbers(text)):
        if _number(token) not in numbers:
            issues.append(ValidationIssue(severity="error", statement=token, reason="Число отсутствует в подтверждённых данных", check="unknown_number"))
    for token in dict.fromkeys(IDENTIFIER.findall(text)):
        if token not in identifiers:
            issues.append(ValidationIssue(severity="error", statement=token, reason="Идентификатор отсутствует в подтверждённых данных", check="unknown_identifier"))
    for token in dict.fromkeys(DATE.findall(text)):
        if token not in dates:
            issues.append(ValidationIssue(severity="error", statement=token, reason="Дата отсутствует в подтверждённых данных", check="unknown_date"))
    return ValidationResult(valid=not issues, issues=issues)


def _number(value: str) -> Decimal | None:
    try:
        return Decimal(value.replace(" ", "").replace("\u00a0", "").replace(",", ".")).normalize()
    except InvalidOperation:
        return None


def _report_numbers(text: str):
    for match in NUMBER.finditer(text):
        line_start = text.rfind("\n", 0, match.start()) + 1
        prefix = text[line_start:match.start()]
        suffix = text[match.end():match.end() + 1]
        if not prefix.strip() and suffix in {".", ")"}:
            continue
        yield match.group()


def _text_values(value: Any):
    if isinstance(value, dict):
        for item in value.values():
            yield from _text_values(item)
    elif isinstance(value, list):
        for item in value:
            yield from _text_values(item)
    elif value is not None:
        yield str(value)

"""Parsing and deterministic matching for physical-audit workbook evidence."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from io import BytesIO
from numbers import Number
from typing import Any

from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Asset, AuditMatchReason, AuditMatchStrategy
from .system_imports import (
    ImportValidationError,
    _json_value,
    _text,
    _validate_xlsx_archive,
    normalize_asset_code,
    original_asset_code,
)

AUDIT_HEADERS = (
    "CANTIDAD",
    "IDENTIFICACION",
    "MAQUINA/EQUIPO",
    "MARCA",
    "MODELO ",
    "FUNCIONAMIENTO",
    "ESTADO EXTERNO",
    "OBSERVACIONES",
    "EXISTENCIA EN BRIDGE",
    "CC FISICO",
    "CC  BG",
)


@dataclass(frozen=True)
class ParsedAuditRow:
    """One physical-audit row and the complete positional source evidence."""

    named_values: dict[str, Any]
    original_data: dict[str, Any]
    quantity: Decimal
    identifier: str


@dataclass(frozen=True)
class ParsedAuditReport:
    rows: tuple[ParsedAuditRow, ...]
    sheet_names: tuple[str, ...]


@dataclass(frozen=True)
class AuditMatch:
    candidate_asset: Asset | None
    strategy: AuditMatchStrategy | None
    reason: AuditMatchReason | None


def _is_blank_row(values: tuple[Any, ...]) -> bool:
    return not any(_text(value) for value in values)


def _quantity(value: Any) -> Decimal:
    """Accept only source numeric, positive whole-unit audit quantities."""
    if isinstance(value, bool) or not isinstance(value, Number):
        raise ImportValidationError("invalid_quantity", "every CANTIDAD value must be a positive integer")
    quantity = Decimal(str(value))
    if not quantity.is_finite() or quantity <= 0 or quantity != quantity.to_integral_value():
        raise ImportValidationError("invalid_quantity", "every CANTIDAD value must be a positive integer")
    return quantity


def parse_audit_report(content: bytes) -> ParsedAuditReport:
    """Read only sheets with the exact physical-audit row-three layout."""
    _validate_xlsx_archive(content)
    workbook = None
    try:
        workbook = load_workbook(filename=BytesIO(content), read_only=True, data_only=False)
        rows: list[ParsedAuditRow] = []
        audit_sheets: list[str] = []
        for worksheet in workbook.worksheets:
            header_values = tuple(next(worksheet.iter_rows(min_row=3, max_row=3, values_only=True), ()) or ())
            headers = tuple("" if value is None else str(value) for value in header_values)
            present = [header for header in AUDIT_HEADERS if header in headers]
            if not present:
                # Embedded Bridge/system sheets are reference-only unless they
                # look like an attempted physical-audit layout.
                continue
            missing = [header for header in AUDIT_HEADERS if header not in headers]
            duplicates = [header for header in AUDIT_HEADERS if headers.count(header) != 1]
            positioned = tuple(headers[index] if index < len(headers) else "" for index in range(len(AUDIT_HEADERS)))
            if missing or duplicates or positioned != AUDIT_HEADERS:
                raise ImportValidationError(
                    "invalid_audit_layout",
                    "each audit sheet must contain the required physical-audit headers exactly once in A:K on row 3",
                )
            audit_sheets.append(worksheet.title)
            indexes = {header: headers.index(header) for header in AUDIT_HEADERS}
            for source_row, values in enumerate(worksheet.iter_rows(min_row=4, values_only=True), start=4):
                if _is_blank_row(values):
                    continue
                cells = [
                    {
                        "column": index + 1,
                        "header": _json_value(header_values[index]) if index < len(header_values) else None,
                        "value": _json_value(values[index]) if index < len(values) else None,
                    }
                    for index in range(max(len(header_values), len(values)))
                ]
                named_values = {
                    header: _json_value(values[index] if index < len(values) else None)
                    for header, index in indexes.items()
                }
                rows.append(
                    ParsedAuditRow(
                        named_values=named_values,
                        original_data={"source_sheet": worksheet.title, "source_row": source_row, "cells": cells},
                        quantity=_quantity(named_values["CANTIDAD"]),
                        identifier=original_asset_code(named_values["IDENTIFICACION"]),
                    )
                )
        if not audit_sheets:
            raise ImportValidationError("no_audit_sheets", "workbook contains no physical-audit sheets")
        if not rows:
            raise ImportValidationError("no_usable_rows", "workbook contains no usable audit rows")
        workbook.close()
        workbook = None
        return ParsedAuditReport(rows=tuple(rows), sheet_names=tuple(audit_sheets))
    except ImportValidationError:
        raise
    except Exception as error:
        raise ImportValidationError("unreadable_workbook", "file is not a readable .xlsx workbook") from error
    finally:
        if workbook is not None:
            try:
                workbook.close()
            except Exception:
                pass


def match_audit_identifier(db: Session, identifier: str) -> AuditMatch:
    """Match only exact original code, then one unique normalized code."""
    if not identifier.strip():
        return AuditMatch(None, None, AuditMatchReason.MISSING_IDENTIFIER)
    exact = db.scalar(select(Asset).where(Asset.original_code == identifier))
    if exact is not None:
        return AuditMatch(exact, AuditMatchStrategy.EXACT_ORIGINAL_CODE, None)
    candidates = list(db.scalars(select(Asset).where(Asset.normalized_code == normalize_asset_code(identifier))))
    if not candidates:
        return AuditMatch(None, None, AuditMatchReason.NO_NORMALIZED_CANDIDATE)
    if len(candidates) != 1:
        return AuditMatch(None, None, AuditMatchReason.AMBIGUOUS_NORMALIZED_CANDIDATE)
    return AuditMatch(candidates[0], AuditMatchStrategy.NORMALIZED_CODE, None)

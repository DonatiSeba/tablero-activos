"""Conservative manual-to-BG links for mixed historical physical-audit evidence."""

from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from typing import Iterable

from .audit_imports import ParsedAuditRow
from .models import HistoricalFoundLinkReason, HistoricalFoundLinkStrategy


MIN_EMBEDDED_TOKEN_ALNUM_LENGTH = 6


@dataclass(frozen=True)
class HistoricalFoundLink:
    """One non-mutating relationship outcome for a manual source row."""

    bg_index: int | None
    strategy: HistoricalFoundLinkStrategy | None
    reason: HistoricalFoundLinkReason | None


def _raw_bg_value(row: ParsedAuditRow, column: int) -> str:
    cells = row.original_data.get("cells")
    if not isinstance(cells, list) or column > len(cells):
        return ""
    value = cells[column - 1].get("value") if isinstance(cells[column - 1], dict) else None
    return "" if value is None else str(value)


def _without_whitespace(value: str) -> str:
    return "".join(value.split())


def _embedded_token(value: str) -> str:
    token = "".join(character for character in unicodedata.normalize("NFKC", value).upper() if character.isalnum())
    # NS is a label, not part of a manually recorded serial identifier.
    return token[2:] if token.startswith("NS") else token


def _unique_outcome(candidates: Iterable[int], strategy: HistoricalFoundLinkStrategy) -> HistoricalFoundLink | None:
    unique = sorted(set(candidates))
    if len(unique) == 1:
        return HistoricalFoundLink(unique[0], strategy, None)
    if len(unique) > 1:
        return HistoricalFoundLink(None, None, HistoricalFoundLinkReason.AMBIGUOUS_BG_CANDIDATE)
    return None


def link_historical_found_rows(manual_rows: list[ParsedAuditRow], bg_rows: list[ParsedAuditRow]) -> list[HistoricalFoundLink]:
    """Link each manual row only through a unique, ordered conservative route."""
    outcomes: list[HistoricalFoundLink] = []
    bg_codes = [_raw_bg_value(row, 4) for row in bg_rows]
    bg_identifiers = [_raw_bg_value(row, 5) for row in bg_rows]
    for manual in manual_rows:
        identifier = manual.identifier
        exact = _unique_outcome(
            (index for index, code in enumerate(bg_codes) if identifier and code == identifier),
            HistoricalFoundLinkStrategy.EXACT_BG_CODE,
        )
        if exact is not None:
            outcomes.append(exact)
            continue
        normalized_identifier = _without_whitespace(identifier)
        whitespace_normalized = _unique_outcome(
            (
                index
                for index, code in enumerate(bg_codes)
                if normalized_identifier and _without_whitespace(code) == normalized_identifier
            ),
            HistoricalFoundLinkStrategy.WHITESPACE_NORMALIZED_BG_CODE,
        )
        if whitespace_normalized is not None:
            outcomes.append(whitespace_normalized)
            continue
        token = _embedded_token(identifier)
        if len(token) < MIN_EMBEDDED_TOKEN_ALNUM_LENGTH:
            outcomes.append(HistoricalFoundLink(None, None, HistoricalFoundLinkReason.NO_BG_CANDIDATE))
            continue
        embedded = _unique_outcome(
            (
                index
                for index, (code, bg_identifier) in enumerate(zip(bg_codes, bg_identifiers, strict=True))
                if token in _embedded_token(code) or token in _embedded_token(bg_identifier)
            ),
            HistoricalFoundLinkStrategy.EMBEDDED_IDENTIFIER_OR_SERIAL,
        )
        outcomes.append(embedded or HistoricalFoundLink(None, None, HistoricalFoundLinkReason.NO_BG_CANDIDATE))
    return outcomes

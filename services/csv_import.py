"""CSV-Import-Hilfsfunktionen: Spalten-Auto-Erkennung + Vorschau vor dem
eigentlichen Import (Abschnitt 7 "Drag & Drop, Vorschau, automatische
Spaltenerkennung, Kennzeichnung ungueltiger Nummern")."""

from __future__ import annotations

import csv
import io

from services.lead_service import is_valid_phone_number

CANONICAL_FIELDS = (
    "unternehmen",
    "ansprechpartner",
    "branche",
    "website_url",
    "telefonnummer",
    "email",
    "notizen",
    "online_auftritt_geprueft",
    "entwurf_vorhanden",
    "entwurf_link",
)

_ALIASES: dict[str, list[str]] = {
    "unternehmen": ["unternehmen", "firma", "firmenname", "company", "company name", "betrieb"],
    "ansprechpartner": [
        "ansprechpartner", "kontaktperson", "contact person", "contactperson",
        "kontakt", "ansprechperson", "name ansprechpartner",
    ],
    "branche": ["branche", "industry", "kategorie", "sector"],
    "website_url": ["website", "webseite", "url", "homepage", "web"],
    "telefonnummer": ["telefonnummer", "telefon", "phone", "nummer", "rufnummer", "tel", "mobil", "handynummer"],
    "email": ["email", "e-mail", "mail", "e mail"],
    "notizen": ["notizen", "notes", "bemerkung", "anmerkung", "kommentar"],
    "online_auftritt_geprueft": ["online-auftritt geprueft", "online auftritt geprueft", "website geprueft"],
    "entwurf_vorhanden": ["entwurf vorhanden", "entwurf"],
    "entwurf_link": ["entwurf link", "entwurf-link", "entwurfslink"],
}


def _normalize_header(header: str) -> str:
    return header.strip().lower().replace("_", " ")


def detect_columns(headers: list[str]) -> dict[str, str]:
    """Gibt canonical_field -> tatsaechlicher CSV-Header zurueck (nur fuer
    erkannte Felder)."""
    normalized = {h: _normalize_header(h) for h in headers}
    mapping: dict[str, str] = {}
    for field, aliases in _ALIASES.items():
        for header, norm in normalized.items():
            if norm in aliases:
                mapping[field] = header
                break
    return mapping


def parse_csv_bytes(raw: bytes) -> tuple[list[str], list[dict[str, str]]]:
    text = raw.decode("utf-8-sig")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=";,\t")
    except csv.Error:
        dialect = csv.excel
        dialect.delimiter = ";" if text[:4096].count(";") > text[:4096].count(",") else ","
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    headers = reader.fieldnames or []
    rows = [dict(row) for row in reader]
    return headers, rows


def build_preview(raw: bytes) -> dict:
    headers, raw_rows = parse_csv_bytes(raw)
    mapping = detect_columns(headers)

    preview_rows = []
    for raw_row in raw_rows:
        data = {}
        for field in CANONICAL_FIELDS:
            source_header = mapping.get(field)
            data[field] = (raw_row.get(source_header, "") or "").strip() if source_header else ""

        errors = []
        if not data["unternehmen"]:
            errors.append("Unternehmen fehlt")
        if not data["telefonnummer"]:
            errors.append("Telefonnummer fehlt")
        elif not is_valid_phone_number(data["telefonnummer"]):
            errors.append(f"Ungueltige Telefonnummer: {data['telefonnummer']}")

        preview_rows.append({"data": data, "valid": not errors, "errors": errors})

    return {
        "headers": headers,
        "columns_detected": mapping,
        "rows": preview_rows,
        "total": len(preview_rows),
        "valid_count": sum(1 for r in preview_rows if r["valid"]),
        "invalid_count": sum(1 for r in preview_rows if not r["valid"]),
    }

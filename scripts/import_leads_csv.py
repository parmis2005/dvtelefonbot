"""CSV-Import fuer Leads (Abschnitt 54).

Aufruf:
    python -m scripts.import_leads_csv --file leads.csv

Erwartete Spalten (Header-Zeile, Reihenfolge egal, fehlende optionale Spalten
sind erlaubt):
    unternehmen, ansprechpartner, telefonnummer, branche, website_url,
    online_auftritt_geprueft, entwurf_vorhanden, entwurf_link, email, notizen
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import sys

from database.database import get_session_factory, init_db
from services.lead_service import LeadService


async def run_import(path: str) -> None:
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = [row for row in reader]

    if not rows:
        print("Keine Zeilen in der CSV-Datei gefunden.")
        return

    await init_db()
    session_factory = get_session_factory()
    async with session_factory() as session:
        service = LeadService(session)
        created, errors = await service.import_from_rows(rows)

    print(f"Import abgeschlossen: {len(created)} Leads angelegt, {len(errors)} Fehler.")
    for err in errors:
        print(f"  FEHLER: {err}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Lead-Import per CSV")
    parser.add_argument("--file", required=True, help="Pfad zur CSV-Datei")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        asyncio.run(run_import(args.file))
    except FileNotFoundError:
        print(f"Datei nicht gefunden: {args.file}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

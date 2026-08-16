"""Test 17 (Abschnitt 60): E-Mail-Normalisierung aus gesprochenem Text."""

from __future__ import annotations

from agent.nlu import extract_email, normalize_spoken_email


def test_spoken_email_is_normalized():
    assert normalize_spoken_email("info at firma punkt de") == "info@firma.de"


def test_spoken_email_with_dash_and_underscore():
    assert normalize_spoken_email("max minus mustermann at firma punkt de") == "max-mustermann@firma.de"


def test_direct_email_is_extracted_without_change():
    assert extract_email("Meine Adresse ist info@firma.de") == "info@firma.de"


def test_extract_email_handles_spoken_form_in_sentence():
    result = extract_email("also das waere info at beispielfirma punkt de gewesen")
    assert result == "info@beispielfirma.de"


def test_no_email_returns_none():
    assert extract_email("Ich habe gerade keine Zeit.") is None

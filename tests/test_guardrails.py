"""Tests 4, 5, 6, 7 (Abschnitt 60): harte Wahrheitsregeln."""

from __future__ import annotations

import pytest

from agent.context import LeadData
from agent.guardrails import (
    GuardrailViolation,
    assert_can_claim_entwurf_vorhanden,
    assert_can_claim_online_auftritt_geprueft,
    can_claim_entwurf_vorhanden,
    can_claim_online_auftritt_geprueft,
    guard_callback,
    guard_send_email,
    is_valid_email,
)
from agent.responses import ResponseBank
from core.config import BusinessConfig


def _bank() -> ResponseBank:
    return ResponseBank("Dario", "Digital Vision", "Moenchengladbach", BusinessConfig({}))


# --- Test 4: kein Entwurf -> keine Entwurfsbehauptung ----------------------


def test_no_design_means_no_design_claim():
    lead = LeadData(entwurf_vorhanden=False)
    assert can_claim_entwurf_vorhanden(lead) is False
    with pytest.raises(GuardrailViolation):
        assert_can_claim_entwurf_vorhanden(lead)


def test_response_bank_never_claims_design_without_one():
    bank = _bank()
    lead = LeadData(entwurf_vorhanden=False)
    assert bank.offer_design_no_website(lead) is None
    assert bank.offer_design_existing_website(lead) is None
    assert bank.offer_design_as_comparison(lead) is None
    assert bank.offer_design_despite_rejection(lead) is None


def test_response_bank_offers_design_when_present():
    bank = _bank()
    lead = LeadData(entwurf_vorhanden=True, entwurf_link="https://x.de/entwurf")
    assert bank.offer_design_no_website(lead) is not None


# --- Test 5: Online-Auftritt nicht geprueft -> keine Pruefbehauptung ------


def test_website_not_checked_means_no_check_claim():
    lead = LeadData(online_auftritt_geprueft=False)
    assert can_claim_online_auftritt_geprueft(lead) is False
    with pytest.raises(GuardrailViolation):
        assert_can_claim_online_auftritt_geprueft(lead)


def test_response_bank_avoids_check_claim_when_not_checked():
    bank = _bank()
    lead = LeadData(online_auftritt_geprueft=False)
    text = bank.website_check_intro(lead)
    assert "angesehen" not in text


def test_response_bank_makes_check_claim_when_checked():
    bank = _bank()
    lead = LeadData(online_auftritt_geprueft=True)
    text = bank.website_check_intro(lead)
    assert "angesehen" in text


# --- Test 6: E-Mail-Fehler -> keine falsche Versandbestaetigung ------------


def test_guard_send_email_fails_without_valid_email():
    lead = LeadData(email="", entwurf_link="https://x.de/entwurf")
    allowed, _reason = guard_send_email(lead)
    assert allowed is False


def test_guard_send_email_fails_without_design_link():
    lead = LeadData(email="info@firma.de", entwurf_link="")
    allowed, _reason = guard_send_email(lead)
    assert allowed is False


def test_guard_send_email_passes_with_valid_data():
    lead = LeadData(email="info@firma.de", entwurf_link="https://x.de/entwurf")
    allowed, _reason = guard_send_email(lead)
    assert allowed is True


def test_is_valid_email():
    assert is_valid_email("info@firma.de") is True
    assert is_valid_email("nicht-valide") is False
    assert is_valid_email(None) is False


# --- Test 7: Termin ohne Kalender -> keine Buchungsbestaetigung -----------


def test_guard_callback_requires_note():
    allowed, _ = guard_callback(None)
    assert allowed is False
    allowed, _ = guard_callback("Dienstag Nachmittag")
    assert allowed is True


def test_callback_without_calendar_never_confirms_fixed_booking():
    bank = _bank()
    text = bank.callback_without_calendar()
    assert "fest gebucht" not in text
    assert "Bestaetigung" in text

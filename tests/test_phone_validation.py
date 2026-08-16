"""Test 18 (Abschnitt 60): Telefonnummernvalidierung."""

from __future__ import annotations

from agent.guardrails import is_valid_phone
from services.lead_service import is_valid_phone_number, normalize_phone


def test_normalize_german_local_number_to_e164():
    assert normalize_phone("0170 1234567") == "+491701234567"


def test_normalize_00_prefix_to_plus():
    assert normalize_phone("0049 170 1234567") == "+491701234567"


def test_normalize_already_e164():
    assert normalize_phone("+49 170 1234567") == "+491701234567"


def test_valid_phone_number_accepted():
    assert is_valid_phone_number("+491701234567") is True
    assert is_valid_phone_number("0170 1234567") is True


def test_invalid_phone_number_rejected():
    assert is_valid_phone_number("keine nummer") is False
    assert is_valid_phone_number("123") is False


def test_guardrail_is_valid_phone_requires_e164_like_format():
    assert is_valid_phone("+491701234567") is True
    assert is_valid_phone("nicht valide") is False
    assert is_valid_phone(None) is False

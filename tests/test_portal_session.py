import pytest
from portal_session import detect_provider


def test_detect_hefame_uppercase():
    assert detect_provider("HEF-2024-001234") == "hefame"


def test_detect_hefame_lowercase():
    assert detect_provider("hef001234") == "hefame"


def test_detect_bida_uppercase():
    assert detect_provider("BID-001234") == "bida"


def test_detect_bida_lowercase():
    assert detect_provider("bid12345") == "bida"


def test_detect_unknown_lab():
    assert detect_provider("COSMED-2024-001") == "unknown"


def test_detect_empty_string():
    assert detect_provider("") == "unknown"


def test_detect_pure_digits_unknown():
    # Dígitos puros sin prefijo reconocido → unknown hasta inspección real
    assert detect_provider("123456789") == "unknown"

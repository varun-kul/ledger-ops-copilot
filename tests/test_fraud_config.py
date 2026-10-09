import json

from app.fraud.config import load_expected_countries
from app.fraud.rules import detect_geo_mismatch
from app.db.models import NormalizedTransaction, SourceName
from datetime import datetime, timezone


def _txn(country):
    return NormalizedTransaction(
        txn_ref="TXN-X", source=SourceName.LIVE_STREAM, amount_cents=5000,
        currency="USD", ts=datetime.now(timezone.utc), status="posted",
        raw={"country": country},
    )


def test_load_expected_countries_reads_real_config():
    countries = load_expected_countries()
    assert "US" in countries
    assert "GB" in countries


def test_load_expected_countries_falls_back_when_file_missing(tmp_path):
    missing_path = tmp_path / "does_not_exist.json"
    result = load_expected_countries(missing_path)
    assert result == {"US", "GB"}


def test_load_expected_countries_falls_back_on_malformed_json(tmp_path):
    bad_path = tmp_path / "bad.json"
    bad_path.write_text("{not valid json")
    result = load_expected_countries(bad_path)
    assert result == {"US", "GB"}


def test_load_expected_countries_falls_back_on_empty_list(tmp_path):
    empty_path = tmp_path / "empty.json"
    empty_path.write_text(json.dumps({"expected_countries": []}))
    result = load_expected_countries(empty_path)
    assert result == {"US", "GB"}


def test_geo_mismatch_uses_config_by_default():
    # NG is in the real config (config/meridian_pay.json) as of cycle 2 --
    # this test will need updating if that config changes, which is the point
    flags = detect_geo_mismatch([_txn("NG")])
    assert flags == []


def test_geo_mismatch_explicit_override_ignores_config():
    flags = detect_geo_mismatch([_txn("NG")], expected_countries={"US"})
    assert len(flags) == 1
    assert flags[0].txn_refs == ["TXN-X"]
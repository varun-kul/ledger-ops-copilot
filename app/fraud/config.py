"""
Loads per-customer configuration (currently just expected_countries for the
geo_mismatch fraud rule). See docs/feedback-log.md cycle 2 for why this
exists: a hardcoded country allow-list breaks every time the customer opens
a new market, which is exactly what happened with Meridian Pay's Lagos
office.

Falls back to a safe hardcoded default if the config file is missing or
malformed -- same "never hard-fail on missing config" pattern as the rest
of the project (stripe_source.py's fixture fallback, llm_client.py's
FallbackClient, slack.py's stdout fallback).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "meridian_pay.json"
_FALLBACK_EXPECTED_COUNTRIES = {"US", "GB"}


def load_expected_countries(config_path: str | Path = DEFAULT_CONFIG_PATH) -> set[str]:
    path = Path(config_path)
    if not path.exists():
        logger.warning("customer config not found at %s -- using fallback expected countries %s",
                        path, _FALLBACK_EXPECTED_COUNTRIES)
        return set(_FALLBACK_EXPECTED_COUNTRIES)

    try:
        with open(path) as f:
            data = json.load(f)
        countries = set(data["expected_countries"])
        if not countries:
            raise ValueError("expected_countries is empty")
        return countries
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        logger.error("customer config at %s is malformed (%s) -- using fallback %s",
                      path, e, _FALLBACK_EXPECTED_COUNTRIES)
        return set(_FALLBACK_EXPECTED_COUNTRIES)
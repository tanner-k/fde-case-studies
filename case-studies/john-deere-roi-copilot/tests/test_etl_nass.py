"""Tests for the USDA NASS Quick Stats extractor.

No API key was available when this was written, so nothing here is an
end-to-end proof. What is pinned is everything that does not need one: the
request the extractor builds, and how it reads a response body. The response
fixture is SYNTHETIC — hand-written to the documented Quick Stats record shape,
not captured from the live API. The one behaviour verified against the live
service is the unauthorized error body, which needs no key to observe.
"""

import json
from pathlib import Path

import pytest
from etl import nass

FIXTURES = Path(__file__).parent / "fixtures" / "etl"
SYNTHETIC = json.loads((FIXTURES / "nass_county_yield_SYNTHETIC.json").read_text())


def test_missing_key_names_the_variable_and_where_to_get_one():
    with pytest.raises(nass.MissingApiKeyError) as exc:
        nass.api_key(env={})
    message = str(exc.value)
    assert "NASS_API_KEY" in message
    assert "https://quickstats.nass.usda.gov/api" in message


def test_blank_key_is_treated_as_missing():
    with pytest.raises(nass.MissingApiKeyError):
        nass.api_key(env={"NASS_API_KEY": "   "})


def test_present_key_is_returned_stripped():
    assert nass.api_key(env={"NASS_API_KEY": " abc123 "}) == "abc123"


def test_county_yield_query_targets_iowa_counties_with_year_operators():
    params = nass.build_params(nass.COUNTY_YIELD, key="k", start_year=2006, end_year=2025)
    assert params["key"] == "k"
    assert params["format"] == "JSON"
    assert params["state_alpha"] == "IA"
    assert params["agg_level_desc"] == "COUNTY"
    assert params["statisticcat_desc"] == "YIELD"
    assert params["year__GE"] == "2006"
    assert params["year__LE"] == "2025"
    assert set(nass.COMMODITIES) == {"CORN", "SOYBEANS"}


def test_price_query_is_state_level_because_nass_publishes_no_county_price():
    assert nass.STATE_PRICE.params["agg_level_desc"] == "STATE"
    params = nass.build_params(nass.STATE_PRICE, key="k", start_year=2006, end_year=2025)
    assert params["statisticcat_desc"] == "PRICE RECEIVED"
    assert params["agg_level_desc"] == "STATE"


def test_build_params_rejects_a_reversed_year_range():
    with pytest.raises(ValueError, match="start_year"):
        nass.build_params(nass.COUNTY_YIELD, key="k", start_year=2025, end_year=2006)


def test_response_parses_into_a_tidy_frame():
    frame = nass.parse_response(SYNTHETIC)
    assert frame.columns == list(nass.NORMALIZED_COLUMNS)
    assert frame.height == 3
    assert frame["county_name"].to_list() == ["STORY", "BOONE", "STORY"]
    assert frame["year"].to_list() == [2024, 2024, 2024]


def test_thousands_separators_are_parsed_and_suppression_codes_become_null():
    """`(D)` is NASS's disclosure suppression marker — a null, never a zero."""
    frame = nass.parse_response(SYNTHETIC)
    values = frame["value"].to_list()
    assert values[0] == pytest.approx(203.4)
    assert values[1] == pytest.approx(1203.0)
    assert values[2] is None


def test_an_unrecognised_non_numeric_value_is_an_error_not_a_quiet_null():
    """Nulling an unknown marker would corrupt the panel invisibly."""
    payload = {"data": [{**SYNTHETIC["data"][0], "Value": "roughly 200"}]}
    with pytest.raises(nass.QuickStatsError, match="roughly 200"):
        nass.parse_response(payload)


def test_unauthorized_body_raises_an_actionable_error():
    """This is the live response for a missing or bad key — verified, HTTP 401."""
    with pytest.raises(nass.QuickStatsError) as exc:
        nass.parse_response({"error": ["unauthorized"]})
    assert "unauthorized" in str(exc.value)
    assert "NASS_API_KEY" in str(exc.value)


def test_a_body_without_a_data_array_is_rejected_rather_than_silently_empty():
    with pytest.raises(nass.QuickStatsError, match="data"):
        nass.parse_response({"unexpected": []})
    with pytest.raises(nass.QuickStatsError):
        nass.parse_response([])


def test_a_record_missing_a_required_field_fails_loudly():
    broken = {"data": [{"year": 2024, "Value": "1"}]}
    with pytest.raises(nass.QuickStatsError, match="county_name"):
        nass.parse_response(broken)


def test_hitting_the_record_cap_is_treated_as_truncation_not_success():
    """50,000 rows back means the query was clipped; the panel would be wrong."""
    with pytest.raises(nass.QuickStatsError, match="truncat"):
        nass.parse_response(SYNTHETIC, record_limit=3)


def test_the_default_record_limit_matches_the_documented_api_cap():
    assert nass.RECORD_LIMIT == 50_000


# --- Regressions found on the first live run (2026-08-11) -------------------
# Both were invisible against synthetic fixtures and would have silently
# corrupted the fitted yield priors.


def _record(**overrides: object) -> dict[str, object]:
    """A Quick Stats record shaped like the real API's, with fields overridden."""
    return {**SYNTHETIC["data"][0], **overrides}


def test_corn_yield_query_restricts_to_grain_not_silage():
    """Silage yield is TONS/ACRE and would be averaged in with BU/ACRE grain."""
    params = nass.build_params(
        nass.COUNTY_YIELD, key="k", start_year=2020, end_year=2021, commodity="CORN"
    )
    assert params.get("util_practice_desc") == "GRAIN"


def test_soybean_yield_query_omits_the_corn_only_utilization_filter():
    params = nass.build_params(
        nass.COUNTY_YIELD, key="k", start_year=2020, end_year=2021, commodity="SOYBEANS"
    )
    assert "util_practice_desc" not in params


def test_other_counties_pseudo_rows_are_dropped():
    """NASS buckets disclosure-suppressed counties into a phantom FIPS ...998."""
    payload = {
        "data": [
            _record(county_code="001", county_name="ADAIR", value="200.1"),
            _record(county_code="998", county_name="OTHER (COMBINED) COUNTIES", value="180.0"),
            _record(county_code="998", county_name="OTHER COUNTIES", value="175.0"),
        ]
    }
    frame = nass.parse_response(payload)
    assert frame.height == 1
    assert frame["county_name"].to_list() == ["ADAIR"]

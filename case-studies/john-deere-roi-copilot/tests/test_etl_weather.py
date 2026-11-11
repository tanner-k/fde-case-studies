"""Tests for the Open-Meteo historical weather extractor.

The archive fixture is a real recorded response (Story County centroid, three
days of May 2024) with `generationtime_ms` stripped so it is stable. The
gazetteer fixture is a real excerpt of the Census county gazetteer, tabs and
trailing header whitespace intact.

The footgun this file exists to pin: omitting the unit parameters returns
Celsius and millimetres with no error and no visible difference in the numbers'
plausibility. The parser therefore asserts the units from `daily_units` rather
than trusting the request it just sent.
"""

import json
from datetime import date
from pathlib import Path

import pytest
from etl import weather

FIXTURES = Path(__file__).parent / "fixtures" / "etl"
ARCHIVE = json.loads((FIXTURES / "open_meteo_story_county_2024-05.json").read_text())
GAZETTEER = (FIXTURES / "gazetteer_sample.txt").read_text()

STORY = weather.Centroid(fips="19169", name="Story County", latitude=42.03, longitude=-93.46)


def test_request_states_units_explicitly_rather_than_taking_the_defaults():
    params = weather.build_params(STORY, date(2024, 5, 1), date(2024, 5, 3))
    assert params["temperature_unit"] == "fahrenheit"
    assert params["precipitation_unit"] == "inch"
    assert params["daily"] == "temperature_2m_max,temperature_2m_min,precipitation_sum"
    assert params["start_date"] == "2024-05-01"
    assert params["end_date"] == "2024-05-03"
    assert params["latitude"] == "42.03"


def test_build_params_rejects_a_reversed_date_range():
    with pytest.raises(ValueError, match="start"):
        weather.build_params(STORY, date(2024, 5, 3), date(2024, 5, 1))


def test_archive_response_parses_into_a_tidy_daily_frame():
    frame = weather.parse_archive(ARCHIVE, STORY)
    assert frame.columns == list(weather.NORMALIZED_COLUMNS)
    assert frame.height == 3
    assert frame["county_fips"].to_list() == ["19169"] * 3
    assert frame["tmax_f"][0] == pytest.approx(64.9)
    assert frame["tmin_f"][2] == pytest.approx(44.0)
    assert frame["precip_in"][1] == pytest.approx(1.346)
    assert str(frame["date"][0]) == "2024-05-01"


def test_grid_snap_is_recorded_so_the_11km_offset_is_auditable():
    """The API answers from the nearest grid cell, not the requested point."""
    frame = weather.parse_archive(ARCHIVE, STORY)
    assert frame["grid_latitude"][0] == pytest.approx(42.003513)
    assert frame["grid_longitude"][0] == pytest.approx(-93.40613)


def test_celsius_response_is_rejected_instead_of_being_silently_ingested():
    payload = json.loads(json.dumps(ARCHIVE))
    payload["daily_units"]["temperature_2m_max"] = "°C"
    with pytest.raises(weather.UnitMismatchError) as exc:
        weather.parse_archive(payload, STORY)
    assert "temperature_2m_max" in str(exc.value)
    assert "°C" in str(exc.value)
    assert "°F" in str(exc.value)


def test_millimetre_response_is_rejected_too():
    payload = json.loads(json.dumps(ARCHIVE))
    payload["daily_units"]["precipitation_sum"] = "mm"
    with pytest.raises(weather.UnitMismatchError, match="precipitation_sum"):
        weather.parse_archive(payload, STORY)


def test_a_missing_daily_units_block_is_an_error_not_an_assumption():
    payload = {k: v for k, v in ARCHIVE.items() if k != "daily_units"}
    with pytest.raises(weather.ArchiveError, match="daily_units"):
        weather.parse_archive(payload, STORY)


def test_ragged_series_are_rejected():
    payload = json.loads(json.dumps(ARCHIVE))
    payload["daily"]["precipitation_sum"] = [0.1]
    with pytest.raises(weather.ArchiveError, match="length"):
        weather.parse_archive(payload, STORY)


def test_an_api_error_body_is_surfaced():
    body = {"error": True, "reason": "Value cannot be negative"}
    with pytest.raises(weather.ArchiveError, match="Value cannot be negative"):
        weather.parse_archive(body, STORY)


def test_gazetteer_yields_only_the_requested_state():
    centroids = weather.parse_gazetteer(GAZETTEER, state="IA")
    assert [c.name for c in centroids] == ["Adair County", "Adams County", "Allamakee County"]
    assert centroids[0].fips == "19001"
    assert centroids[0].latitude == pytest.approx(41.328528)
    assert centroids[0].longitude == pytest.approx(-94.478164)


def test_gazetteer_centroids_land_inside_iowas_bounding_box():
    for centroid in weather.parse_gazetteer(GAZETTEER, state="IA"):
        assert 40.3 < centroid.latitude < 43.6
        assert -96.7 < centroid.longitude < -90.1


def test_gazetteer_missing_a_coordinate_column_fails_loudly():
    broken = "USPS\tGEOID\tNAME\nIA\t19001\tAdair County\n"
    with pytest.raises(weather.GazetteerError, match="INTPTLAT"):
        weather.parse_gazetteer(broken, state="IA")


def test_an_unknown_state_is_an_error_rather_than_an_empty_pull():
    with pytest.raises(weather.GazetteerError, match="ZZ"):
        weather.parse_gazetteer(GAZETTEER, state="ZZ")

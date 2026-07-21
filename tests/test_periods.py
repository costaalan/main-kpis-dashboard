import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from datetime import date
from periods import (
    period_key, period_label, previous_period_key, next_period_key,
    year_ago_period_key, period_delta, absolute_delta,
)


def test_period_key_dia():
    assert period_key("dia", date(2026, 7, 16)) == "2026-07-16"


def test_period_key_semana_iso():
    assert period_key("semana", date(2026, 7, 16)) == "2026-W29"


def test_period_key_mes():
    assert period_key("mes", date(2026, 7, 16)) == "2026-07"


def test_period_label_dia():
    assert period_label("dia", "2026-07-16") == "16-07"


def test_period_label_semana():
    assert period_label("semana", "2026-W29") == "W29-26"


def test_period_label_mes():
    assert period_label("mes", "2026-07") == "Jul-26"


def test_previous_period_key_dia():
    assert previous_period_key("dia", "2026-07-16") == "2026-07-15"


def test_previous_period_key_mes_wraps_year():
    assert previous_period_key("mes", "2026-01") == "2025-12"


def test_previous_period_key_semana_wraps_year():
    assert previous_period_key("semana", "2026-W01") == "2025-W52"


def test_next_period_key_dia():
    assert next_period_key("dia", "2026-07-16") == "2026-07-17"


def test_next_period_key_mes_wraps_year():
    assert next_period_key("mes", "2026-12") == "2027-01"


def test_next_period_key_semana_wraps_year():
    assert next_period_key("semana", "2025-W52") == "2026-W01"


def test_year_ago_period_key_dia():
    assert year_ago_period_key("dia", "2026-07-16") == "2025-07-16"


def test_year_ago_period_key_dia_feb29_falls_back():
    assert year_ago_period_key("dia", "2028-02-29") == "2027-02-28"


def test_year_ago_period_key_mes():
    assert year_ago_period_key("mes", "2026-07") == "2025-07"


def test_year_ago_period_key_semana():
    assert year_ago_period_key("semana", "2026-W29") == "2025-W29"


def test_year_ago_period_key_semana_clamps_to_last_week():
    assert year_ago_period_key("semana", "2020-W53") == "2019-W52"


def test_period_delta_normal():
    assert period_delta(110.0, 100.0) == 0.1


def test_period_delta_none_previous_returns_none():
    assert period_delta(110.0, None) is None


def test_period_delta_zero_previous_returns_none():
    assert period_delta(110.0, 0.0) is None


def test_absolute_delta_normal():
    assert round(absolute_delta(0.03, 0.02), 10) == 0.01


def test_absolute_delta_none_previous_returns_none():
    assert absolute_delta(0.03, None) is None


def test_absolute_delta_zero_previous_returns_raw_difference():
    assert absolute_delta(0.03, 0.0) == 0.03

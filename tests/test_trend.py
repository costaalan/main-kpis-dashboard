import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from trend import linear_regression, classify_trend, project_forward


def test_linear_regression_perfect_line():
    slope, intercept = linear_regression([(0, 10.0), (1, 20.0), (2, 30.0)])
    assert round(slope, 4) == 10.0
    assert round(intercept, 4) == 10.0


def test_linear_regression_empty_returns_zero():
    slope, intercept = linear_regression([])
    assert slope == 0.0
    assert intercept == 0.0


def test_linear_regression_single_point():
    slope, intercept = linear_regression([(0, 42.0)])
    assert slope == 0.0
    assert intercept == 42.0


def test_classify_trend_alta():
    trend, trend_line = classify_trend([(0, 100.0), (1, 110.0), (2, 120.0), (3, 130.0)])
    assert trend == "alta"
    assert len(trend_line) == 4


def test_classify_trend_baixa():
    trend, _ = classify_trend([(0, 130.0), (1, 120.0), (2, 110.0), (3, 100.0)])
    assert trend == "baixa"


def test_classify_trend_estavel_within_threshold():
    trend, _ = classify_trend([(0, 1000.0), (1, 1001.0), (2, 1000.0), (3, 1005.0)])
    assert trend == "estavel"


def test_classify_trend_empty_points_is_estavel():
    trend, trend_line = classify_trend([])
    assert trend == "estavel"
    assert trend_line == []


def test_classify_trend_zero_baseline_rising_is_alta():
    trend, _ = classify_trend([(0, 0.0), (1, 50.0), (2, 100.0)])
    assert trend == "alta"


def test_classify_trend_zero_baseline_flat_is_estavel():
    trend, _ = classify_trend([(0, 0.0), (1, 0.0), (2, 0.0)])
    assert trend == "estavel"


def test_project_forward_continues_the_line():
    projected = project_forward([(0, 10.0), (1, 20.0), (2, 30.0)], 3)
    assert [round(v, 4) for v in projected] == [40.0, 50.0, 60.0]


def test_project_forward_empty_points_returns_empty():
    assert project_forward([], 3) == []


def test_project_forward_zero_periods_returns_empty():
    assert project_forward([(0, 10.0), (1, 20.0)], 0) == []

"""Pure linear regression + alta/estavel/baixa trend classification."""

TREND_THRESHOLD = 0.02  # +-2% projected change over the period => "estavel"


def linear_regression(points):
    n = len(points)
    if n == 0:
        return 0.0, 0.0
    if n == 1:
        return 0.0, points[0][1]

    sum_x = sum(p[0] for p in points)
    sum_y = sum(p[1] for p in points)
    sum_xy = sum(p[0] * p[1] for p in points)
    sum_x2 = sum(p[0] ** 2 for p in points)

    denom = n * sum_x2 - sum_x ** 2
    slope = 0.0 if denom == 0 else (n * sum_xy - sum_x * sum_y) / denom
    intercept = (sum_y - slope * sum_x) / n
    return slope, intercept


def project_forward(points, num_periods):
    if not points or num_periods <= 0:
        return []
    slope, intercept = linear_regression(points)
    last_x = points[-1][0]
    return [slope * (last_x + i) + intercept for i in range(1, num_periods + 1)]


def classify_trend(points):
    if not points:
        return "estavel", []

    slope, intercept = linear_regression(points)
    trend_line = [slope * x + intercept for x, _ in points]

    start_val = trend_line[0]
    end_val = trend_line[-1]

    if start_val == 0:
        if end_val == 0:
            trend = "estavel"
        elif end_val > 0:
            trend = "alta"
        else:
            trend = "baixa"
        return trend, trend_line

    pct_change = (end_val - start_val) / abs(start_val)

    if abs(pct_change) <= TREND_THRESHOLD:
        trend = "estavel"
    elif pct_change > 0:
        trend = "alta"
    else:
        trend = "baixa"

    return trend, trend_line

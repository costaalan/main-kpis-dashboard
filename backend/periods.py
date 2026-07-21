"""Pure period-key/label/delta math for dia|semana|mes granularities."""

from datetime import date, timedelta

_MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def period_key(periodicidade, d):
    if periodicidade == "dia":
        return d.strftime("%Y-%m-%d")
    if periodicidade == "semana":
        iso_year, iso_week, _ = d.isocalendar()
        return f"{iso_year}-W{iso_week:02d}"
    if periodicidade == "mes":
        return f"{d.year}-{d.month:02d}"
    raise ValueError("periodicidade invalida: " + periodicidade)


def period_label(periodicidade, key):
    if periodicidade == "dia":
        y, m, d = key.split("-")
        return f"{d}-{m}"
    if periodicidade == "semana":
        y, w = key.split("-W")
        return f"W{int(w)}-{y[2:]}"
    if periodicidade == "mes":
        y, m = key.split("-")
        return f"{_MONTH_ABBR[int(m) - 1]}-{y[2:]}"
    raise ValueError("periodicidade invalida: " + periodicidade)


def previous_period_key(periodicidade, key):
    if periodicidade == "dia":
        d = date.fromisoformat(key)
        return (d - timedelta(days=1)).strftime("%Y-%m-%d")
    if periodicidade == "semana":
        y, w = key.split("-W")
        monday = date.fromisocalendar(int(y), int(w), 1)
        prev_monday = monday - timedelta(days=7)
        iso_year, iso_week, _ = prev_monday.isocalendar()
        return f"{iso_year}-W{iso_week:02d}"
    if periodicidade == "mes":
        y, m = int(key.split("-")[0]), int(key.split("-")[1])
        if m == 1:
            return f"{y - 1}-12"
        return f"{y}-{m - 1:02d}"
    raise ValueError("periodicidade invalida: " + periodicidade)


def next_period_key(periodicidade, key):
    if periodicidade == "dia":
        d = date.fromisoformat(key)
        return (d + timedelta(days=1)).strftime("%Y-%m-%d")
    if periodicidade == "semana":
        y, w = key.split("-W")
        monday = date.fromisocalendar(int(y), int(w), 1)
        next_monday = monday + timedelta(days=7)
        iso_year, iso_week, _ = next_monday.isocalendar()
        return f"{iso_year}-W{iso_week:02d}"
    if periodicidade == "mes":
        y, m = int(key.split("-")[0]), int(key.split("-")[1])
        if m == 12:
            return f"{y + 1}-01"
        return f"{y}-{m + 1:02d}"
    raise ValueError("periodicidade invalida: " + periodicidade)


def year_ago_period_key(periodicidade, key):
    if periodicidade == "dia":
        d = date.fromisoformat(key)
        try:
            d2 = d.replace(year=d.year - 1)
        except ValueError:
            d2 = d.replace(year=d.year - 1, day=28)
        return d2.strftime("%Y-%m-%d")
    if periodicidade == "semana":
        y, w = key.split("-W")
        target_year = int(y) - 1
        try:
            date.fromisocalendar(target_year, int(w), 1)
            return f"{target_year}-W{w}"
        except ValueError:
            last_week = date(target_year, 12, 28).isocalendar()[1]
            return f"{target_year}-W{last_week:02d}"
    if periodicidade == "mes":
        y, m = key.split("-")
        return f"{int(y) - 1}-{m}"
    raise ValueError("periodicidade invalida: " + periodicidade)


def period_delta(current_value, previous_value):
    if previous_value is None or previous_value == 0:
        return None
    return (current_value - previous_value) / previous_value


def absolute_delta(current_value, previous_value):
    """Raw difference (not relative) — used for KPIs that are already a rate/percentage,
    where a relative delta would be misleading (e.g. CVR 2%->3% is +1 ponto percentual,
    not +50%)."""
    if previous_value is None:
        return None
    return current_value - previous_value

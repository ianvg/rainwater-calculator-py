from tkinter_app import RainwaterTkApp


def test_chart_render_indices_limit_points_and_preserve_extrema() -> None:
    values = [float(index % 100) for index in range(10_000)]
    values[4_321] = -50.0
    values[7_654] = 250.0

    indices = RainwaterTkApp._chart_render_indices(values, max_points=600)

    assert indices == sorted(set(indices))
    assert len(indices) <= 600
    assert indices[0] == 0
    assert indices[-1] == len(values) - 1
    assert 4_321 in indices
    assert 7_654 in indices


def test_acis_station_label_includes_state_name() -> None:
    label = RainwaterTkApp._station_label(
        {"name": "Central Park", "sid": "123", "state": "NY", "provider": "ACIS"}
    )

    assert label == "Central Park - 123 in New York"


def test_eccc_station_label_includes_province_name() -> None:
    label = RainwaterTkApp._station_label(
        {"name": "Toronto", "sid": "456", "state": "ON", "provider": "ECCC"}
    )

    assert label == "Toronto - 456 in Ontario"

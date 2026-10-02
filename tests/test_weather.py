from benchpet.sources.weather import condition
from benchpet.sprites import load_library


def test_condition_priorities():
    assert condition(95, 20, 10, True) == "storm"
    assert condition(73, -2, 10, True) == "snow"
    assert condition(63, 12, 55, True) == "windy_rain"
    assert condition(63, 12, 10, True) == "rain"
    assert condition(53, 12, 10, True) == "drizzle"
    assert condition(2, 15, 50, True) == "windy"
    assert condition(0, 31, 5, True) == "hot"
    assert condition(3, 1, 5, True) == "cold"
    assert condition(0, 18, 5, True) == "sunny"
    assert condition(0, 18, 5, False) == "clear_night"
    assert condition(3, 15, 5, True) == "cloudy"


def test_every_condition_has_an_activity():
    library = load_library()
    for cond in ["storm", "snow", "windy_rain", "rain", "drizzle", "windy", "hot", "cold",
                 "sunny", "clear_night", "cloudy"]:
        assert f"weather_{cond}" in library.activities

import pytest

from matchwise.places import location_matches, parse_place


@pytest.mark.parametrize("place, location, expected", [
    ("Texas", "Houston, TX", True),
    ("Texas", "Austin, Texas Metropolitan Area", True),
    ("TX", "Dallas, TX", True),
    ("Texas", "Austin, MN", False),
    ("Texas", "Greater Houston", False),             # known gap: metro name without a state
    ("Dallas, TX", "Dallas, TX", True),
    ("Dallas, TX", "Dallas, OR", False),             # same city name, other state
    ("Dallas, Texas", "Dallas, TX", True),
    ("Denver", "Denver, CO", True),
    ("Denver", "Denverton, CO", False),              # whole words only
    ("New York", "New York City Metropolitan Area", True),
    ("Bengaluru", "Bengaluru, Karnataka, India", True),
    ("Bengaluru, India", "Bengaluru, Karnataka, India", True),
    ("Austin, TX", None, False),
])
def test_location_matching(place, location, expected):
    assert location_matches(location, parse_place(place)) is expected


def test_remote_is_not_a_place():
    assert parse_place("Remote") is None and parse_place("anywhere") is None


def test_regex_characters_in_places_are_literal():
    assert location_matches("St. Louis, MO", parse_place("St. Louis, MO"))
    assert not location_matches("Stx Louis, MO", parse_place("St. Louis, MO"))

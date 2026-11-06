from weft_core.fips import FIPS_TO_ISO, iso_from_fips


def test_differing_codes_map_correctly() -> None:
    # codes where FIPS 10-4 and ISO 3166 differ, including the beats' countries
    assert iso_from_fips("IS") == "IL" and iso_from_fips("IR") == "IR"
    assert iso_from_fips("UP") == "UA" and iso_from_fips("RS") == "RU"
    assert (
        iso_from_fips("IN") == "IN" and iso_from_fips("UK") == "GB" and iso_from_fips("GM") == "DE"
    )
    assert iso_from_fips("us") == "US" and iso_from_fips("ZZ") is None


def test_every_target_is_two_letters_and_codes_are_unique() -> None:
    assert all(len(v) == 2 and v.isalpha() for v in FIPS_TO_ISO.values())
    assert len(FIPS_TO_ISO) > 200

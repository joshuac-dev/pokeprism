from app.config import Settings


def test_cors_origins_parse_comma_separated_values():
    settings = Settings(CORS_ORIGINS="http://localhost:3000, https://example.test ")

    assert settings.cors_origins_list == [
        "http://localhost:3000",
        "https://example.test",
    ]


def test_cors_origins_allows_explicit_wildcard():
    settings = Settings(CORS_ORIGINS="*")

    assert settings.cors_origins_list == "*"

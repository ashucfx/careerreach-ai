import pytest
from careerreach.auth import AuthConfigurationError, AuthService
from careerreach.config import Settings
from careerreach.schemas import RegistrationRequest
from pydantic import SecretStr, ValidationError


def test_registration_rejects_short_passwords_and_invalid_email() -> None:
    with pytest.raises(ValidationError):
        RegistrationRequest(email="not-an-email", password="short")

    with pytest.raises(ValidationError):
        RegistrationRequest(email="person@example.org", password="too-short")


def test_authentication_requires_database_and_a_strong_signing_key() -> None:
    missing_database = AuthService(Settings(auth_signing_key=SecretStr("x" * 64)))
    with pytest.raises(AuthConfigurationError, match="CAREERREACH_DATABASE_URL"):
        missing_database._credentials()

    short_key = AuthService(
        Settings(
            database_url="postgresql://localhost/careerreach", auth_signing_key=SecretStr("short")
        )
    )
    with pytest.raises(AuthConfigurationError, match="at least 32 bytes"):
        short_key._credentials()

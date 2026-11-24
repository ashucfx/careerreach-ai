from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, cast
from uuid import UUID, uuid4

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt.exceptions import InvalidTokenError as JWTInvalidTokenError
from psycopg import AsyncConnection
from psycopg import Error as PostgresError
from psycopg.errors import UniqueViolation
from psycopg.rows import dict_row
from pwdlib import PasswordHash
from starlette.concurrency import run_in_threadpool

from .config import Settings
from .schemas import AccessToken, LoginRequest, RegistrationRequest, UserIdentity

_BEARER = HTTPBearer(auto_error=False)
_BEARER_DEPENDENCY = Depends(_BEARER)
_PASSWORD_HASH = PasswordHash.recommended()


class JWTCodec(Protocol):
    def encode(self, payload: dict[str, Any], key: str, algorithm: str) -> str: ...

    def decode(
        self,
        token: str,
        key: str,
        *,
        algorithms: Sequence[str],
        audience: str,
        issuer: str,
        options: dict[str, list[str]],
    ) -> dict[str, Any]: ...


_JWT = cast(JWTCodec, jwt)


class AuthConfigurationError(RuntimeError):
    pass


class DuplicateUserError(ValueError):
    pass


class InvalidCredentialsError(ValueError):
    pass


class InvalidTokenError(ValueError):
    pass


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    user: UserIdentity
    session_id: UUID


class AuthService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._dummy_password_hash: str | None = None
        self._dummy_hash_lock = asyncio.Lock()

    def _credentials(self) -> tuple[str, str]:
        if self._settings.database_url is None:
            raise AuthConfigurationError("Set CAREERREACH_DATABASE_URL to use authentication.")
        if self._settings.auth_signing_key is None:
            raise AuthConfigurationError("Set CAREERREACH_AUTH_SIGNING_KEY to use authentication.")
        signing_key = self._settings.auth_signing_key.get_secret_value()
        if len(signing_key.encode("utf-8")) < 32:
            raise AuthConfigurationError("CAREERREACH_AUTH_SIGNING_KEY must be at least 32 bytes.")
        return self._settings.database_url, signing_key

    async def register(self, request: RegistrationRequest) -> UserIdentity:
        database_url, _ = self._credentials()
        email = str(request.email).strip().casefold()
        password_hash = await run_in_threadpool(
            _PASSWORD_HASH.hash, request.password.get_secret_value()
        )
        user_id = uuid4()
        try:
            async with (
                await AsyncConnection.connect(database_url) as connection,
                connection.cursor(row_factory=dict_row) as cursor,
            ):
                await cursor.execute(
                    "INSERT INTO app_user (id, email, password_hash) "
                    "VALUES (%s, %s, %s) RETURNING id, email, created_at",
                    (user_id, email, password_hash),
                )
                row = await cursor.fetchone()
            if row is None:
                raise RuntimeError("User registration did not return a user record.")
            return UserIdentity.model_validate(row)
        except UniqueViolation as exc:
            raise DuplicateUserError("An account with this email already exists.") from exc

    async def login(self, request: LoginRequest) -> AccessToken:
        database_url, signing_key = self._credentials()
        email = str(request.email).strip().casefold()
        async with (
            await AsyncConnection.connect(database_url) as connection,
            connection.cursor(row_factory=dict_row) as cursor,
        ):
            await cursor.execute(
                "SELECT id, email, password_hash, created_at, disabled_at "
                "FROM app_user WHERE lower(email) = %s",
                (email,),
            )
            row = await cursor.fetchone()
        password = request.password.get_secret_value()
        if row is None:
            await self._verify_unknown_user(password)
            raise InvalidCredentialsError("Email or password is incorrect.")
        if row["disabled_at"] is not None:
            await run_in_threadpool(_PASSWORD_HASH.verify, password, row["password_hash"])
            raise InvalidCredentialsError("Email or password is incorrect.")
        verified = await run_in_threadpool(_PASSWORD_HASH.verify, password, row["password_hash"])
        if not verified:
            raise InvalidCredentialsError("Email or password is incorrect.")
        now = datetime.now(UTC)
        expires_at = now + timedelta(minutes=self._settings.auth_token_ttl_minutes)
        session_id = uuid4()
        async with await AsyncConnection.connect(database_url) as connection:
            await connection.execute(
                "INSERT INTO auth_session (id, user_id, issued_at, expires_at) "
                "VALUES (%s, %s, %s, %s)",
                (session_id, row["id"], now, expires_at),
            )
        token = _JWT.encode(
            {
                "sub": str(row["id"]),
                "jti": str(session_id),
                "iss": self._settings.auth_issuer,
                "aud": self._settings.auth_audience,
                "iat": now,
                "exp": expires_at,
            },
            signing_key,
            algorithm="HS256",
        )
        return AccessToken(
            access_token=token,
            expires_in=self._settings.auth_token_ttl_minutes * 60,
        )

    async def authenticate(self, token: str) -> AuthenticatedPrincipal:
        database_url, signing_key = self._credentials()
        try:
            claims = _JWT.decode(
                token,
                signing_key,
                algorithms=["HS256"],
                audience=self._settings.auth_audience,
                issuer=self._settings.auth_issuer,
                options={"require": ["exp", "iat", "sub", "jti", "aud", "iss"]},
            )
            user_id = UUID(claims["sub"])
            session_id = UUID(claims["jti"])
        except (JWTInvalidTokenError, KeyError, TypeError, ValueError) as exc:
            raise InvalidTokenError("Bearer token is invalid or expired.") from exc
        async with (
            await AsyncConnection.connect(database_url) as connection,
            connection.cursor(row_factory=dict_row) as cursor,
        ):
            await cursor.execute(
                "SELECT u.id, u.email, u.created_at "
                "FROM app_user AS u JOIN auth_session AS s ON s.user_id = u.id "
                "WHERE u.id = %s AND s.id = %s AND u.disabled_at IS NULL "
                "AND s.revoked_at IS NULL AND s.expires_at > now()",
                (user_id, session_id),
            )
            row = await cursor.fetchone()
        if row is None:
            raise InvalidTokenError("Bearer token is invalid or expired.")
        return AuthenticatedPrincipal(UserIdentity.model_validate(row), session_id)

    async def revoke(self, principal: AuthenticatedPrincipal) -> None:
        database_url, _ = self._credentials()
        async with await AsyncConnection.connect(database_url) as connection:
            await connection.execute(
                "UPDATE auth_session SET revoked_at = now() "
                "WHERE id = %s AND user_id = %s AND revoked_at IS NULL",
                (principal.session_id, principal.user.id),
            )

    async def _verify_unknown_user(self, password: str) -> None:
        if self._dummy_password_hash is None:
            async with self._dummy_hash_lock:
                if self._dummy_password_hash is None:
                    self._dummy_password_hash = await run_in_threadpool(
                        _PASSWORD_HASH.hash, uuid4().hex
                    )
        await run_in_threadpool(_PASSWORD_HASH.verify, password, self._dummy_password_hash)


async def get_current_principal(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = _BEARER_DEPENDENCY,
) -> AuthenticatedPrincipal:
    if credentials is None or credentials.scheme.casefold() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    service: AuthService = request.app.state.auth_service
    try:
        return await service.authenticate(credentials.credentials)
    except InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except AuthConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except PostgresError as exc:
        raise HTTPException(status_code=503, detail="The account database is unavailable.") from exc

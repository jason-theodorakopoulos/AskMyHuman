"""Bounded OpenID and JWKS validation for ACS callback bearer tokens."""

import asyncio
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import cast
from urllib.parse import urlsplit

import httpx
import jwt
from jwt import InvalidTokenError, PyJWK

from ask_my_human.errors import AskMyHumanError, ErrorCode

ACS_OPENID_CONFIGURATION_URL = (
    "https://acscallautomation.communication.azure.com/calling/.well-known/acsopenidconfiguration"
)
MAX_TOKEN_BYTES = 16_384
MAX_DOCUMENT_BYTES = 262_144
MAX_JWKS_KEYS = 32
MAX_CACHE_TTL_SECONDS = 3_600.0
MAX_REQUEST_TIMEOUT_SECONDS = 10.0
REFRESH_COOLDOWN_SECONDS = 30.0


@dataclass(frozen=True, slots=True)
class _Metadata:
    issuer: str
    jwks_uri: str
    expires_at: float


@dataclass(frozen=True, slots=True)
class _KeySet:
    keys: dict[str, PyJWK]
    expires_at: float


class AcsCallbackTokenValidator:
    """Validate ACS callback tokens using bounded, replace-on-refresh caches."""

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        audience: str,
        *,
        openid_configuration_url: str = ACS_OPENID_CONFIGURATION_URL,
        cache_ttl_seconds: float = 300.0,
        request_timeout_seconds: float = 5.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not 0 < cache_ttl_seconds <= MAX_CACHE_TTL_SECONDS:
            raise ValueError("cache_ttl_seconds is outside the supported range")
        if not 0 < request_timeout_seconds <= MAX_REQUEST_TIMEOUT_SECONDS:
            raise ValueError("request_timeout_seconds is outside the supported range")
        if not audience:
            raise ValueError("audience must not be empty")
        self._http_client = http_client
        self._audience = audience
        self._openid_configuration_url = openid_configuration_url
        self._cache_ttl_seconds = cache_ttl_seconds
        self._request_timeout_seconds = request_timeout_seconds
        self._clock = clock
        self._metadata: _Metadata | None = None
        self._key_set: _KeySet | None = None
        self._refresh_lock = asyncio.Lock()
        self._next_fetch: dict[str, float] = {}

    async def validate(self, authorization: str | None) -> None:
        try:
            async with asyncio.timeout(self._request_timeout_seconds):
                await self._validate(authorization)
        except TimeoutError:
            raise _authentication_unavailable() from None

    async def _validate(self, authorization: str | None) -> None:
        token = _bearer_token(authorization)
        key_id = _token_key_id(token)
        metadata = await self._get_metadata()
        key_set = await self._get_key_set(metadata)
        signing_key = key_set.keys.get(key_id)
        if signing_key is None:
            key_set = await self._refresh_key_set(metadata, expected=key_set)
            signing_key = key_set.keys.get(key_id)
        if signing_key is None:
            raise _invalid_token()

        try:
            jwt.decode(
                token,
                key=signing_key.key,
                algorithms=["RS256"],
                audience=self._audience,
                issuer=metadata.issuer,
                options={"require": ["aud", "exp", "iss"]},
            )
        except InvalidTokenError:
            raise _invalid_token() from None

    async def _get_metadata(self) -> _Metadata:
        cached = self._metadata
        if cached is not None and cached.expires_at > self._clock():
            return cached
        async with self._refresh_lock:
            cached = self._metadata
            if cached is not None and cached.expires_at > self._clock():
                return cached
            document = await self._fetch_json(self._openid_configuration_url)
            issuer = document.get("issuer")
            jwks_uri = document.get("jwks_uri")
            if (
                not isinstance(issuer, str)
                or not issuer
                or not isinstance(jwks_uri, str)
                or urlsplit(jwks_uri).scheme != "https"
            ):
                raise _authentication_unavailable()
            metadata = _Metadata(
                issuer=issuer,
                jwks_uri=jwks_uri,
                expires_at=self._clock() + self._cache_ttl_seconds,
            )
            self._metadata = metadata
            self._key_set = None
            return metadata

    async def _get_key_set(self, metadata: _Metadata) -> _KeySet:
        cached = self._key_set
        if cached is not None and cached.expires_at > self._clock():
            return cached
        return await self._refresh_key_set(metadata, expected=cached)

    async def _refresh_key_set(
        self,
        metadata: _Metadata,
        *,
        expected: _KeySet | None,
    ) -> _KeySet:
        async with self._refresh_lock:
            cached = self._key_set
            if cached is not expected and cached is not None and cached.expires_at > self._clock():
                return cached
            if (
                cached is not None
                and cached.expires_at > self._clock()
                and self._next_fetch.get(metadata.jwks_uri, 0) > self._clock()
            ):
                return cached
            document = await self._fetch_json(metadata.jwks_uri)
            raw_keys = document.get("keys")
            if not isinstance(raw_keys, list) or len(raw_keys) > MAX_JWKS_KEYS:
                raise _authentication_unavailable()
            parsed_keys: dict[str, PyJWK] = {}
            try:
                for raw_key in raw_keys:
                    if not isinstance(raw_key, dict):
                        raise ValueError
                    key_id = raw_key.get("kid")
                    if not isinstance(key_id, str) or not key_id or key_id in parsed_keys:
                        raise ValueError
                    parsed_key = PyJWK.from_dict(raw_key)
                    if parsed_key.algorithm_name != "RS256":
                        raise ValueError
                    parsed_keys[key_id] = parsed_key
            except (InvalidTokenError, KeyError, TypeError, ValueError):
                raise _authentication_unavailable() from None
            key_set = _KeySet(
                keys=parsed_keys,
                expires_at=self._clock() + self._cache_ttl_seconds,
            )
            self._key_set = key_set
            return key_set

    async def _fetch_json(self, url: str) -> dict[str, object]:
        if self._next_fetch.get(url, 0) > self._clock():
            raise _authentication_unavailable()
        self._next_fetch[url] = self._clock() + REFRESH_COOLDOWN_SECONDS
        try:
            async with self._http_client.stream(
                "GET",
                url,
                timeout=self._request_timeout_seconds,
                follow_redirects=False,
                headers={"Accept-Encoding": "identity"},
            ) as response:
                response.raise_for_status()
                if response.headers.get("content-encoding", "identity") != "identity":
                    raise ValueError
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(content) + len(chunk) > MAX_DOCUMENT_BYTES:
                        raise ValueError
                    content.extend(chunk)
            document = cast(object, json.loads(content))
        except (httpx.HTTPError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
            raise _authentication_unavailable() from None
        if not isinstance(document, dict) or not all(isinstance(key, str) for key in document):
            raise _authentication_unavailable()
        return document


def _bearer_token(authorization: str | None) -> str:
    if not authorization or len(authorization) > MAX_TOKEN_BYTES + len("Bearer "):
        raise _invalid_token()
    scheme, separator, token = authorization.partition(" ")
    if scheme.casefold() != "bearer" or not separator or not token or " " in token:
        raise _invalid_token()
    return token


def _token_key_id(token: str) -> str:
    try:
        header = jwt.get_unverified_header(token)
    except InvalidTokenError:
        raise _invalid_token() from None
    key_id = header.get("kid")
    algorithm = header.get("alg")
    if not isinstance(key_id, str) or not key_id or algorithm != "RS256":
        raise _invalid_token()
    return key_id


def _invalid_token() -> AskMyHumanError:
    return AskMyHumanError(ErrorCode.UNAUTHENTICATED, "invalid callback token")


def _authentication_unavailable() -> AskMyHumanError:
    return AskMyHumanError(ErrorCode.DEPENDENCY_FAILURE, "callback authentication unavailable")

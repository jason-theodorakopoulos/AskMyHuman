import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from ask_my_human.errors import AskMyHumanError, ErrorCode
from ask_my_human.security.acs_callback import AcsCallbackTokenValidator

ISSUER = "https://issuer.example.com"
AUDIENCE = "https://audience.example.com"
OPENID_URL = "https://openid.example.com/configuration"
JWKS_URL = "https://openid.example.com/keys"


def _key(key_id: str) -> tuple[rsa.RSAPrivateKey, dict[str, Any]]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = json.loads(RSAAlgorithm.to_jwk(private_key.public_key()))
    public_jwk.update({"kid": key_id, "alg": "RS256", "use": "sig"})
    return private_key, public_jwk


def _token(
    private_key: rsa.RSAPrivateKey,
    key_id: str,
    *,
    issuer: str = ISSUER,
    audience: str = AUDIENCE,
    expires_at: datetime | None = None,
) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "iss": issuer,
            "aud": audience,
            "iat": now,
            "exp": expires_at or now + timedelta(minutes=5),
        },
        private_key,
        algorithm="RS256",
        headers={"kid": key_id},
    )


def _client(
    key_documents: list[list[dict[str, Any]]],
    *,
    on_request: Callable[[httpx.Request], None] | None = None,
) -> httpx.AsyncClient:
    requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        if on_request is not None:
            on_request(request)
        if request.url == httpx.URL(OPENID_URL):
            return httpx.Response(200, json={"issuer": ISSUER, "jwks_uri": JWKS_URL})
        if request.url == httpx.URL(JWKS_URL):
            document = key_documents[min(requests, len(key_documents) - 1)]
            requests += 1
            return httpx.Response(200, json={"keys": document})
        return httpx.Response(404)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_validates_signature_and_uses_cached_metadata_and_keys() -> None:
    private_key, public_jwk = _key("key-1")
    request_urls: list[str] = []
    async with _client(
        [[public_jwk]],
        on_request=lambda request: request_urls.append(str(request.url)),
    ) as client:
        validator = AcsCallbackTokenValidator(
            client,
            AUDIENCE,
            openid_configuration_url=OPENID_URL,
        )
        authorization = f"Bearer {_token(private_key, 'key-1')}"

        await validator.validate(authorization)
        await validator.validate(authorization)

    assert request_urls == [OPENID_URL, JWKS_URL]


@pytest.mark.asyncio
async def test_refreshes_jwks_once_for_rotated_key() -> None:
    old_private_key, old_public_jwk = _key("old-key")
    new_private_key, new_public_jwk = _key("new-key")
    del old_private_key
    request_urls: list[str] = []
    async with _client(
        [[old_public_jwk], [new_public_jwk]],
        on_request=lambda request: request_urls.append(str(request.url)),
    ) as client:
        validator = AcsCallbackTokenValidator(
            client,
            AUDIENCE,
            openid_configuration_url=OPENID_URL,
        )

        await validator.validate(f"Bearer {_token(new_private_key, 'new-key')}")

    assert request_urls == [OPENID_URL, JWKS_URL, JWKS_URL]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("issuer", "audience", "expires_at"),
    [
        ("https://wrong-issuer.example.com", AUDIENCE, None),
        (ISSUER, "https://wrong-audience.example.com", None),
        (ISSUER, AUDIENCE, datetime.now(UTC) - timedelta(seconds=1)),
    ],
)
async def test_rejects_invalid_registered_claims(
    issuer: str,
    audience: str,
    expires_at: datetime | None,
) -> None:
    private_key, public_jwk = _key("key-1")
    async with _client([[public_jwk]]) as client:
        validator = AcsCallbackTokenValidator(
            client,
            AUDIENCE,
            openid_configuration_url=OPENID_URL,
        )

        with pytest.raises(AskMyHumanError) as error:
            await validator.validate(
                "Bearer "
                + _token(
                    private_key,
                    "key-1",
                    issuer=issuer,
                    audience=audience,
                    expires_at=expires_at,
                )
            )

    assert error.value.code is ErrorCode.UNAUTHENTICATED


@pytest.mark.asyncio
async def test_rejects_wrong_signature_without_sensitive_error_text() -> None:
    signing_key, _ = _key("key-1")
    _, trusted_public_jwk = _key("key-1")
    token = _token(signing_key, "key-1")
    async with _client([[trusted_public_jwk]]) as client:
        validator = AcsCallbackTokenValidator(
            client,
            AUDIENCE,
            openid_configuration_url=OPENID_URL,
        )

        with pytest.raises(AskMyHumanError) as error:
            await validator.validate(f"Bearer {token}")

    assert error.value.code is ErrorCode.UNAUTHENTICATED
    assert token not in error.value.message


@pytest.mark.asyncio
async def test_maps_discovery_network_failure_to_retryable_dependency_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("network unavailable", request=request)

    private_key, _ = _key("key-1")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        validator = AcsCallbackTokenValidator(
            client,
            AUDIENCE,
            openid_configuration_url=OPENID_URL,
        )

        with pytest.raises(AskMyHumanError) as error:
            await validator.validate(f"Bearer {_token(private_key, 'key-1')}")

    assert error.value.code is ErrorCode.DEPENDENCY_FAILURE
    assert error.value.retryable is True


@pytest.mark.asyncio
async def test_rejects_missing_bearer_token_without_network_access() -> None:
    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        return httpx.Response(500, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        validator = AcsCallbackTokenValidator(client, AUDIENCE)

        with pytest.raises(AskMyHumanError) as error:
            await validator.validate(None)

    assert error.value.code is ErrorCode.UNAUTHENTICATED
    assert request_count == 0

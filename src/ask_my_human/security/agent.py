"""Authorization for trusted Azure Container Apps principal headers."""

import asyncio
import base64
import binascii
import json
from collections.abc import Collection, Mapping
from typing import Any, Protocol

import jwt
from jwt import PyJWKClient

from ask_my_human.domain.models import Principal
from ask_my_human.errors import AskMyHumanError, ErrorCode

REQUIRED_ROLE = "AskHuman.Invoke"
MAX_PRINCIPAL_HEADER_BYTES = 16_384

_APPLICATION_ID_CLAIMS = (
    "appid",
    "azp",
    "http://schemas.microsoft.com/identity/claims/appid",
)
_OBJECT_ID_CLAIMS = (
    "http://schemas.microsoft.com/identity/claims/objectidentifier",
    "oid",
)
_SUBJECT_ID_CLAIMS = (
    "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/nameidentifier",
    "sub",
)
_ROLE_CLAIMS = (
    "roles",
    "role",
    "http://schemas.microsoft.com/ws/2008/06/identity/claims/role",
)


class SigningKey(Protocol):
    key: Any


class SigningKeyClient(Protocol):
    def get_signing_key_from_jwt(self, token: str) -> SigningKey: ...


class AgentBearerTokenValidator:
    """Validate Entra application tokens when Easy Auth omits its principal header."""

    def __init__(
        self,
        tenant_id: str,
        audience: str,
        authorized_application_ids: Collection[str],
        *,
        signing_keys: SigningKeyClient | None = None,
    ) -> None:
        self._tenant_id = tenant_id
        self._audiences = (audience, f"api://{audience}")
        self._authorized_application_ids = authorized_application_ids
        self._signing_keys = signing_keys or PyJWKClient(
            f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys"
        )

    async def validate(self, authorization: str | None) -> Principal:
        token = _bearer_token(authorization)
        try:
            signing_key = await asyncio.to_thread(
                self._signing_keys.get_signing_key_from_jwt, token
            )
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=self._audiences,
                issuer=(
                    f"https://sts.windows.net/{self._tenant_id}/",
                    f"https://login.microsoftonline.com/{self._tenant_id}/v2.0",
                ),
                options={"require": ["exp", "iat", "nbf", "iss", "aud"]},
            )
        except (jwt.PyJWTError, AttributeError, ValueError):
            raise _unauthenticated() from None
        return _principal_from_claim_values(
            {key: [value] if isinstance(value, str) else value for key, value in claims.items()},
            self._authorized_application_ids,
        )


def parse_container_apps_principal(
    encoded_principal: str | None,
    authorized_application_ids: Collection[str],
) -> Principal:
    """Parse a principal header that Container Apps authentication has validated."""
    payload = _decode_principal(encoded_principal)
    if payload.get("auth_typ") != "aad":
        raise _unauthenticated()

    claims = payload.get("claims")
    if not isinstance(claims, list):
        raise _unauthenticated()

    claim_values: dict[str, list[str]] = {}
    for claim in claims:
        if not isinstance(claim, dict):
            raise _unauthenticated()
        claim_type = claim.get("typ")
        claim_value = claim.get("val")
        if (
            not isinstance(claim_type, str)
            or not isinstance(claim_value, str)
            or not claim_type.strip()
            or not claim_value.strip()
        ):
            raise _unauthenticated()
        claim_values.setdefault(claim_type, []).append(claim_value)

    return _principal_from_claim_values(claim_values, authorized_application_ids)


def _principal_from_claim_values(
    claim_values: Mapping[str, object], authorized_application_ids: Collection[str]
) -> Principal:
    normalized = {
        key: [item for item in value if isinstance(item, str)]
        for key, value in claim_values.items()
        if isinstance(value, list)
    }
    application_id = _single_claim(normalized, _APPLICATION_ID_CLAIMS)
    subject_id = _single_claim(normalized, _OBJECT_ID_CLAIMS) or _single_claim(
        normalized, _SUBJECT_ID_CLAIMS
    )
    if application_id is None or subject_id is None:
        raise _unauthenticated()

    roles = {value for claim_type in _ROLE_CLAIMS for value in normalized.get(claim_type, ())}
    if REQUIRED_ROLE not in roles:
        raise AskMyHumanError(ErrorCode.FORBIDDEN, "agent is not authorized")

    allowed_ids = {item.casefold() for item in authorized_application_ids}
    if application_id.casefold() not in allowed_ids:
        raise AskMyHumanError(ErrorCode.FORBIDDEN, "agent is not authorized")

    return Principal(subject_id=subject_id, application_id=application_id)


def _bearer_token(authorization: str | None) -> str:
    if authorization is None:
        raise _unauthenticated()
    scheme, separator, token = authorization.partition(" ")
    if scheme.casefold() != "bearer" or not separator or not token or " " in token:
        raise _unauthenticated()
    return token


def _decode_principal(encoded_principal: str | None) -> dict[str, object]:
    if not encoded_principal or len(encoded_principal) > MAX_PRINCIPAL_HEADER_BYTES:
        raise _unauthenticated()
    try:
        decoded = base64.b64decode(encoded_principal, validate=True)
        payload: object = json.loads(decoded)
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError):
        raise _unauthenticated() from None
    if not isinstance(payload, dict) or not all(isinstance(key, str) for key in payload):
        raise _unauthenticated()
    return payload


def _single_claim(
    claims: dict[str, list[str]],
    claim_types: tuple[str, ...],
) -> str | None:
    values = {value for claim_type in claim_types for value in claims.get(claim_type, ())}
    if len(values) > 1:
        raise _unauthenticated()
    return next(iter(values), None)


def _unauthenticated() -> AskMyHumanError:
    return AskMyHumanError(ErrorCode.UNAUTHENTICATED, "authentication required")

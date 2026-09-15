"""Authorization for trusted Azure Container Apps principal headers."""

import base64
import binascii
import json
from collections.abc import Collection

from ask_my_human.domain.models import Principal
from ask_my_human.errors import AskMyHumanError, ErrorCode

REQUIRED_ROLE = "AskHuman.Invoke"
MAX_PRINCIPAL_HEADER_BYTES = 16_384

_APPLICATION_ID_CLAIMS = (
    "appid",
    "azp",
    "http://schemas.microsoft.com/identity/claims/appid",
)
_SUBJECT_ID_CLAIMS = (
    "http://schemas.microsoft.com/identity/claims/objectidentifier",
    "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/nameidentifier",
    "oid",
    "sub",
)
_ROLE_CLAIMS = (
    "roles",
    "role",
    "http://schemas.microsoft.com/ws/2008/06/identity/claims/role",
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
        if not isinstance(claim_type, str) or not isinstance(claim_value, str):
            raise _unauthenticated()
        claim_values.setdefault(claim_type, []).append(claim_value)

    application_id = _single_claim(claim_values, _APPLICATION_ID_CLAIMS)
    subject_id = _single_claim(claim_values, _SUBJECT_ID_CLAIMS)
    if application_id is None or subject_id is None:
        raise _unauthenticated()

    roles = {value for claim_type in _ROLE_CLAIMS for value in claim_values.get(claim_type, ())}
    if REQUIRED_ROLE not in roles:
        raise AskMyHumanError(ErrorCode.FORBIDDEN, "agent is not authorized")

    allowed_ids = {item.casefold() for item in authorized_application_ids}
    if application_id.casefold() not in allowed_ids:
        raise AskMyHumanError(ErrorCode.FORBIDDEN, "agent is not authorized")

    return Principal(subject_id=subject_id, application_id=application_id)


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

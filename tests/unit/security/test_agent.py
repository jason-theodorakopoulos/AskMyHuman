import base64
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from ask_my_human.errors import AskMyHumanError, ErrorCode
from ask_my_human.security.agent import AgentBearerTokenValidator, parse_container_apps_principal

ROLE_CLAIM = "http://schemas.microsoft.com/ws/2008/06/identity/claims/role"
SUBJECT_CLAIM = "http://schemas.microsoft.com/identity/claims/objectidentifier"


@dataclass
class _SigningKey:
    key: Any


class _SigningKeys:
    def __init__(self, key: Any) -> None:
        self.key = key

    def get_signing_key_from_jwt(self, token: str) -> _SigningKey:
        return _SigningKey(self.key)


def _token(
    private_key: Any,
    *,
    application_id: str = "agent-app",
    role: str = "AskHuman.Invoke",
    audience: str = "api://api-app",
    issuer: str = "https://sts.windows.net/tenant/",
) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "aud": audience,
            "iss": issuer,
            "iat": now,
            "nbf": now - timedelta(seconds=1),
            "exp": now + timedelta(minutes=5),
            "appid": application_id,
            "oid": "agent-subject",
            "roles": [role],
        },
        private_key,
        algorithm="RS256",
    )


def _header(*, application_id: str = "agent-app", role: str = "AskHuman.Invoke") -> str:
    payload = {
        "auth_typ": "aad",
        "claims": [
            {"typ": "appid", "val": application_id},
            {"typ": SUBJECT_CLAIM, "val": "agent-subject"},
            {"typ": ROLE_CLAIM, "val": role},
        ],
    }
    return base64.b64encode(json.dumps(payload).encode()).decode()


def test_parses_trusted_principal_for_authorized_agent() -> None:
    principal = parse_container_apps_principal(_header(), {"agent-app"})

    assert principal.subject_id == "agent-subject"
    assert principal.application_id == "agent-app"


def test_object_identity_takes_precedence_over_pairwise_subject() -> None:
    payload = json.loads(base64.b64decode(_header()))
    payload["claims"].append({"typ": "sub", "val": "pairwise-subject"})
    header = base64.b64encode(json.dumps(payload).encode()).decode()
    assert parse_container_apps_principal(header, {"agent-app"}).subject_id == "agent-subject"


@pytest.mark.parametrize("header", [None, "", "not-base64", base64.b64encode(b"[]").decode()])
def test_rejects_missing_or_malformed_principal(header: str | None) -> None:
    with pytest.raises(AskMyHumanError) as error:
        parse_container_apps_principal(header, {"agent-app"})

    assert error.value.code is ErrorCode.UNAUTHENTICATED


@pytest.mark.parametrize("claim_type", ["appid", SUBJECT_CLAIM])
def test_blank_identity_claims_are_not_authenticated(claim_type: str) -> None:
    payload = json.loads(base64.b64decode(_header()))
    for claim in payload["claims"]:
        if claim["typ"] == claim_type:
            claim["val"] = " "
    header = base64.b64encode(json.dumps(payload).encode()).decode()
    with pytest.raises(AskMyHumanError) as error:
        parse_container_apps_principal(header, {"agent-app"})
    assert error.value.code is ErrorCode.UNAUTHENTICATED
    assert "agent-subject" not in error.value.message


def test_rejects_principal_without_required_role() -> None:
    with pytest.raises(AskMyHumanError) as error:
        parse_container_apps_principal(_header(role="Other.Role"), {"agent-app"})

    assert error.value.code is ErrorCode.FORBIDDEN


def test_rejects_principal_outside_client_allowlist() -> None:
    with pytest.raises(AskMyHumanError) as error:
        parse_container_apps_principal(_header(application_id="other-app"), {"agent-app"})

    assert error.value.code is ErrorCode.FORBIDDEN


def test_rejects_ambiguous_application_identity() -> None:
    payload = json.loads(base64.b64decode(_header()))
    payload["claims"].append({"typ": "azp", "val": "different-app"})
    header = base64.b64encode(json.dumps(payload).encode()).decode()

    with pytest.raises(AskMyHumanError) as error:
        parse_container_apps_principal(header, {"agent-app"})

    assert error.value.code is ErrorCode.UNAUTHENTICATED


async def test_validates_signed_bearer_token_for_authorized_agent() -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    validator = AgentBearerTokenValidator(
        "tenant",
        "api-app",
        {"agent-app"},
        signing_keys=_SigningKeys(private_key.public_key()),
    )

    principal = await validator.validate(f"Bearer {_token(private_key)}")

    assert principal.subject_id == "agent-subject"
    assert principal.application_id == "agent-app"


@pytest.mark.parametrize(
    ("token_overrides", "expected"),
    [
        ({"application_id": "other-app"}, ErrorCode.FORBIDDEN),
        ({"role": "Other.Role"}, ErrorCode.FORBIDDEN),
        ({"audience": "api://other-api"}, ErrorCode.UNAUTHENTICATED),
        ({"issuer": "https://issuer.example/tenant"}, ErrorCode.UNAUTHENTICATED),
    ],
)
async def test_rejects_invalid_bearer_claims(
    token_overrides: dict[str, str], expected: ErrorCode
) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    validator = AgentBearerTokenValidator(
        "tenant",
        "api-app",
        {"agent-app"},
        signing_keys=_SigningKeys(private_key.public_key()),
    )

    with pytest.raises(AskMyHumanError) as error:
        await validator.validate(f"Bearer {_token(private_key, **token_overrides)}")

    assert error.value.code is expected


@pytest.mark.parametrize("authorization", [None, "", "Basic token", "Bearer", "Bearer a b"])
async def test_rejects_malformed_bearer_authorization(authorization: str | None) -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    validator = AgentBearerTokenValidator(
        "tenant",
        "api-app",
        {"agent-app"},
        signing_keys=_SigningKeys(private_key.public_key()),
    )

    with pytest.raises(AskMyHumanError) as error:
        await validator.validate(authorization)

    assert error.value.code is ErrorCode.UNAUTHENTICATED


async def test_rejects_bearer_token_with_untrusted_signature() -> None:
    trusted_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    attacker_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    validator = AgentBearerTokenValidator(
        "tenant",
        "api-app",
        {"agent-app"},
        signing_keys=_SigningKeys(trusted_key.public_key()),
    )

    with pytest.raises(AskMyHumanError) as error:
        await validator.validate(f"Bearer {_token(attacker_key)}")

    assert error.value.code is ErrorCode.UNAUTHENTICATED

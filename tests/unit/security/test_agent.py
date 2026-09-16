import base64
import json

import pytest

from ask_my_human.errors import AskMyHumanError, ErrorCode
from ask_my_human.security.agent import parse_container_apps_principal

ROLE_CLAIM = "http://schemas.microsoft.com/ws/2008/06/identity/claims/role"
SUBJECT_CLAIM = "http://schemas.microsoft.com/identity/claims/objectidentifier"


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

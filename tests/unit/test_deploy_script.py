"""Run release gates with isolated command stubs, never Azure or real credentials."""

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/deploy_azure.sh"
SOURCE = "a" * 40
DIGEST = "sha256:" + "b" * 64
IMAGE = "registry.invalid/ask-my-human@" + DIGEST
REVISION = "reviewed-app--" + SOURCE[:12] + "-" + "b" * 12
SUBSCRIPTION = "00000000-0000-0000-0000-000000000000"

STUB = r"""
import json
import os
import sys
import tarfile
from pathlib import Path

command = Path(sys.argv[0]).name
arguments = sys.argv[1:]
with open(os.environ["STUB_LOG"], "a") as log:
    log.write(json.dumps({"command": command, "args": arguments,
                          "image": os.environ.get("CONTAINER_IMAGE"),
                          "revision_suffix": os.environ.get("REVISION_SUFFIX")}) + "\n")
if command == "timeout":
    os.execv("/usr/bin/timeout", ["timeout", *arguments])
elif command == "git":
    if arguments[:1] == ["rev-parse"]:
        print(os.environ.get("STUB_HEAD", os.environ["SOURCE_SHA"]))
    elif arguments[:1] == ["status"]:
        print(os.environ.get("STUB_DIRTY", ""), end="")
    elif arguments[:1] == ["archive"]:
        with tarfile.open(fileobj=sys.stdout.buffer, mode="w|"):
            pass
    else:
        sys.exit(99)
elif command == "az":
    if os.environ.get("STUB_AZ_FAIL"):
        print("PRIVATE_AZURE_DIAGNOSTIC", file=sys.stderr)
        sys.exit(1)
    if arguments[:3] == ["deployment", "group", "what-if"]:
        print(os.environ["STUB_WHAT_IF"])
    elif arguments[:2] == ["acr", "build"]:
        print(json.dumps({"status": "Succeeded", "outputImages": [{
            "registry": "registry.invalid", "repository": "ask-my-human",
            "tag": os.environ["SOURCE_SHA"],
            "digest": os.environ.get("STUB_DIGEST", "sha256:" + "b" * 64)}]}))
    elif arguments[:3] == ["deployment", "group", "create"]:
        print(json.dumps({"properties": {"provisioningState": "Succeeded", "outputs": {
            "containerAppName": {"value": os.environ["CONTAINER_APP_NAME"]}}}}))
    elif arguments[:2] == ["containerapp", "show"]:
        print(os.environ["STUB_APP"])
    elif arguments[:3] == ["containerapp", "revision", "show"]:
        print(os.environ["STUB_REVISION"])
    else:
        sys.exit(99)
elif command == "curl":
    if os.environ.get("STUB_CURL_FAIL"):
        sys.exit(28)
    if "--config" in arguments:
        config = sys.stdin.read()
        assert "Authorization: Bearer dummy-health-token" in config
        print(os.environ.get("STUB_HEALTH", "200"), end="")
    else:
        print(os.environ.get("STUB_ANONYMOUS", "401"), end="")
else:
    sys.exit(99)
"""


@dataclass
class Deployment:
    directory: Path
    env: dict[str, str]

    def run(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["/bin/bash", str(SCRIPT), *arguments],
            cwd=self.directory,
            env=self.env,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )

    def write_json(self, name: str, content: object) -> str:
        path = self.directory / name
        path.write_text(json.dumps(content))
        return str(path)

    def review(self, *arguments: str) -> dict[str, Any]:
        result = self.run("what-if", *arguments)
        assert result.returncode == 0, result.stderr
        review: dict[str, Any] = json.loads(result.stdout)
        return review

    def approve(self, binding: dict[str, Any], *, release: bool = False) -> dict[str, Any]:
        record = {
            "record": "external-approval-record",
            "approver": "release-owner",
            "expires_at": "2099-01-01T00:00:00Z",
            "binding": binding,
            "decisions": {f"DR-0{number}": "approved-evidence" for number in range(1, 6)},
        }
        variable = "RELEASE_APPROVAL_FILE" if release else "MUTATION_APPROVAL_FILE"
        self.env[variable] = self.write_json(variable + ".json", record)
        return record

    def published(self) -> None:
        self.env["CONTAINER_IMAGE"] = IMAGE
        self.env["BUILD_RECORD_FILE"] = self.write_json(
            "build.json", {"source": "az acr build", "source_sha": SOURCE, "image": IMAGE}
        )

    def verification(self) -> dict[str, Any]:
        self.published()
        binding: dict[str, Any] = self.review()["binding"]
        self.env["REVIEWED_WHAT_IF_SHA256"] = binding["what_if_sha256"]
        self.env["REVIEWED_PARAMETERS_SHA256"] = binding["parameters_sha256"]
        self.approve(binding)
        self.approve(
            binding | {"revision": REVISION, "endpoint": "https://app.invalid"}, release=True
        )
        return binding

    def calls(self, command: str) -> list[dict[str, Any]]:
        path = Path(self.env["STUB_LOG"])
        if not path.exists():
            return []
        return [
            item
            for line in path.read_text().splitlines()
            if (item := json.loads(line))["command"] == command
        ]


@pytest.fixture
def deployment(tmp_path: Path) -> Deployment:
    tools = tmp_path / "bin"
    tools.mkdir()
    for name in ("az", "git", "curl", "timeout"):
        executable = tools / name
        executable.write_text(f"#!{sys.executable}\n" + STUB)
        executable.chmod(0o700)
    env = {
        "PATH": f"{tools}:/usr/bin:/bin",
        "HOME": str(tmp_path),
        "STUB_LOG": str(tmp_path / "commands.jsonl"),
        "SOURCE_SHA": SOURCE,
        "AZURE_SUBSCRIPTION_ID": SUBSCRIPTION,
        "AZURE_RESOURCE_GROUP": "reviewed-rg",
        "CONTAINER_APP_NAME": "reviewed-app",
        "CONTAINER_REGISTRY_NAME": "registry",
        "CONTAINER_REGISTRY_SERVER": "registry.invalid",
        "CONTAINER_REGISTRY_RESOURCE_ID": (
            f"/subscriptions/{SUBSCRIPTION}/resourceGroups/registry-rg"
            "/providers/Microsoft.ContainerRegistry/registries/registry"
        ),
        "AZURE_LOCATION": "westeurope",
        "POSTGRES_ADMIN_PASSWORD": "dummy-private-password",
        "MY_MOBILE_NUMBER": "+15555550101",
        "ACS_SOURCE_PHONE_NUMBER": "+15555550100",
        "ENTRA_TENANT_ID": SUBSCRIPTION,
        "ENTRA_CLIENT_ID": SUBSCRIPTION,
        "ENTRA_CLIENT_SECRET": "dummy-private-secret",
        "AUTHORIZED_AGENT_APP_IDS": SUBSCRIPTION,
        "EXISTING_ACS_RESOURCE_ID": (
            f"/subscriptions/{SUBSCRIPTION}/resourceGroups/acs-rg"
            "/providers/Microsoft.Communication/communicationServices/acs"
        ),
        "ACS_CALLBACK_AUDIENCE": "verified-immutable-resource-id",
        "ACS_CALLBACK_URL": "https://app.invalid/v1/callbacks/acs",
        "MCP_ALLOWED_HOSTS": "app.invalid",
        "SERVICE_URL": "https://app.invalid",
        "HEALTH_BEARER_TOKEN": "dummy-health-token",
        "EXPECTED_REVISION": REVISION,
        "VERIFY_TIMEOUT_SECONDS": "5",
        "STUB_WHAT_IF": json.dumps(
            {
                "status": "Succeeded",
                "changes": [
                    {
                        "resourceId": (
                            f"/subscriptions/{SUBSCRIPTION}/resourceGroups/reviewed-rg"
                            "/providers/Microsoft.App/containerApps/old-app"
                        ),
                        "changeType": "Delete",
                        "before": {"secret": "DUMMY_WHAT_IF_SECRET"},
                        "delta": [
                            {
                                "path": "properties.configuration.secrets",
                                "propertyChangeType": "Delete",
                                "before": "PRIVATE_VALUE",
                            },
                            {
                                "path": "properties.template.containers",
                                "propertyChangeType": "Modify",
                                "before": {"probes": [{"httpGet": {"path": "/health/live"}}]},
                            },
                        ],
                    }
                ],
            }
        ),
        "STUB_APP": json.dumps(
            {
                "properties": {
                    "latestRevisionName": REVISION,
                    "latestReadyRevisionName": REVISION,
                    "configuration": {
                        "activeRevisionsMode": "Single",
                        "ingress": {
                            "fqdn": "app.invalid",
                            "traffic": [{"latestRevision": True, "weight": 100}],
                        },
                    },
                }
            }
        ),
        "STUB_REVISION": json.dumps(
            {
                "name": REVISION,
                "properties": {
                    "template": {"containers": [{"image": IMAGE}]},
                    "active": True,
                    "runningState": "Running",
                    "healthState": "Healthy",
                    "provisioningState": "Provisioned",
                },
            }
        ),
    }
    return Deployment(tmp_path, env)


@pytest.mark.parametrize("arguments", [(), ("help",), ("--help",), ("-h",)])
def test_default_and_help_need_no_environment_or_commands(arguments: tuple[str, ...]) -> None:
    result = subprocess.run(
        ["/bin/bash", str(SCRIPT), *arguments],
        env={"PATH": "/nonexistent"},
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 0
    assert "Usage:" in result.stdout


def test_what_if_is_reviewable_but_does_not_disclose_values(deployment: Deployment) -> None:
    result = deployment.run("what-if")
    assert result.returncode == 0, result.stderr
    assert '"Delete"' in result.stdout
    assert "properties.configuration.secrets" in result.stdout
    assert "properties.template.containers" in result.stdout
    assert "/health/live" not in result.stdout
    for secret in ("DUMMY_WHAT_IF_SECRET", "PRIVATE_VALUE", "dummy-private", "+1555555"):
        assert secret not in result.stdout + result.stderr
    assert len(deployment.calls("az")) == 1


@pytest.mark.parametrize(
    "metadata",
    [
        {},
        {"status": "Failed", "changes": []},
        {"status": "Succeeded", "changes": [{"resourceId": 123, "changeType": "Delete"}]},
        {
            "status": "Succeeded",
            "changes": [{"resourceId": "/subscriptions/dummy", "changeType": "Unsupported"}],
        },
    ],
)
def test_incomplete_what_if_cannot_be_approved(deployment: Deployment, metadata: object) -> None:
    deployment.env["STUB_WHAT_IF"] = json.dumps(metadata)
    result = deployment.run("what-if")
    assert result.returncode != 0
    assert result.stdout == ""


@pytest.mark.parametrize("dirty", [" M Dockerfile\n", "?? untracked-build-input\n"])
def test_dirty_source_blocks_publication(deployment: Deployment, dirty: str) -> None:
    deployment.env["STUB_DIRTY"] = dirty
    assert deployment.run("publish").returncode != 0
    assert deployment.calls("az") == []


@pytest.mark.parametrize(
    "key,value",
    [
        ("STUB_HEAD", "c" * 40),
        ("CONTAINER_IMAGE", IMAGE),
        ("ACS_CALLBACK_URL", "http://app.invalid"),
        ("ACS_CALLBACK_AUDIENCE", "https://app.invalid"),
    ],
)
def test_invalid_publication_inputs_fail_before_azure(
    deployment: Deployment,
    key: str,
    value: str,
) -> None:
    deployment.env[key] = value
    assert deployment.run("publish").returncode != 0
    assert deployment.calls("az") == []


def test_missing_approval_blocks_publication(deployment: Deployment) -> None:
    assert deployment.run("publish").returncode != 0
    assert deployment.calls("az") == []


@pytest.mark.parametrize("field", ["source_sha", "subscription", "app", "what_if_sha256"])
def test_mismatched_approval_blocks_publication(deployment: Deployment, field: str) -> None:
    binding = deployment.review()["binding"]
    binding[field] = "mismatched"
    deployment.approve(binding)
    result = deployment.run("publish")
    assert result.returncode != 0
    assert all(call["args"][:2] != ["acr", "build"] for call in deployment.calls("az"))


def test_publication_uses_snapshot_and_records_actual_pushed_digest(deployment: Deployment) -> None:
    deployment.approve(deployment.review()["binding"])
    result = deployment.run("publish")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "source": "az acr build",
        "source_sha": SOURCE,
        "image": IMAGE,
    }
    build = next(call for call in deployment.calls("az") if call["args"][:2] == ["acr", "build"])
    assert build["args"][-1] != "."
    assert not Path(build["args"][-1]).exists()
    assert any(call["args"] == ["archive", SOURCE] for call in deployment.calls("git"))


def test_digest_is_deployed_and_health_requires_bearer(deployment: Deployment) -> None:
    deployment.verification()
    result = deployment.run("deploy")
    assert result.returncode == 0, result.stderr
    evidence = json.loads(result.stdout)
    assert evidence["image"] == IMAGE
    assert evidence["revision"] == REVISION
    assert evidence["paid_calls_authorized"] is False
    calls = deployment.calls("az")
    assert all(call["image"] == IMAGE for call in calls)
    assert not any(call["args"][:2] == ["acr", "build"] for call in calls)
    assert any(call["args"][:3] == ["deployment", "group", "create"] for call in calls)
    requests = deployment.calls("curl")
    assert sum("--config" in call["args"] for call in requests) == 2
    assert all(
        "--connect-timeout" in call["args"] and "--max-time" in call["args"] for call in requests
    )
    assert "dummy-health-token" not in result.stdout + result.stderr
    assert all("dummy-health-token" not in str(call["args"]) for call in requests)
    assert all(call["args"][0] == "--kill-after=5" for call in deployment.calls("timeout"))


@pytest.mark.parametrize(
    "field,value",
    [
        ("active", False),
        ("runningState", "Stopped"),
        ("healthState", "Unhealthy"),
        ("provisioningState", "Failed"),
        ("template", {"containers": [{"image": "registry.invalid/old:latest"}]}),
    ],
)
def test_wrong_or_unhealthy_revision_cannot_pass(
    deployment: Deployment,
    field: str,
    value: object,
) -> None:
    deployment.verification()
    deployment.env["VERIFY_TIMEOUT_SECONDS"] = "1"
    metadata = json.loads(deployment.env["STUB_REVISION"])
    metadata["properties"][field] = value
    deployment.env["STUB_REVISION"] = json.dumps(metadata)
    result = deployment.run("verify")
    assert result.returncode != 0
    assert result.stdout == ""
    assert deployment.calls("curl") == []


@pytest.mark.parametrize("field", ["latestRevisionName", "latestReadyRevisionName"])
def test_old_ready_or_current_revision_cannot_pass(deployment: Deployment, field: str) -> None:
    deployment.verification()
    deployment.env["VERIFY_TIMEOUT_SECONDS"] = "1"
    metadata = json.loads(deployment.env["STUB_APP"])
    metadata["properties"][field] = "old-revision"
    deployment.env["STUB_APP"] = json.dumps(metadata)
    assert deployment.run("verify").returncode != 0
    assert deployment.calls("curl") == []


@pytest.mark.parametrize("variable", ["RELEASE_APPROVAL_FILE", "HEALTH_BEARER_TOKEN"])
def test_verification_requires_external_approval_and_token(
    deployment: Deployment, variable: str
) -> None:
    deployment.verification()
    deployment.env.pop(variable)
    result = deployment.run("verify")
    assert result.returncode != 0
    assert result.stdout == ""
    assert deployment.calls("curl") == []


@pytest.mark.parametrize(
    "key,value",
    [
        ("STUB_HEALTH", "503"),
        ("STUB_ANONYMOUS", "200"),
        ("STUB_APP", "{}"),
        ("STUB_REVISION", "not json"),
        ("STUB_CURL_FAIL", "1"),
        ("STUB_AZ_FAIL", "1"),
    ],
)
def test_failed_checks_never_emit_release_evidence(
    deployment: Deployment,
    key: str,
    value: str,
) -> None:
    deployment.verification()
    deployment.env[key] = value
    result = deployment.run("verify")
    assert result.returncode != 0
    assert result.stdout == ""
    assert "PRIVATE_AZURE_DIAGNOSTIC" not in result.stderr


def test_verify_does_not_require_deployment_secrets(deployment: Deployment) -> None:
    deployment.verification()
    for variable in ("POSTGRES_ADMIN_PASSWORD", "ENTRA_CLIENT_SECRET", "MY_MOBILE_NUMBER"):
        deployment.env.pop(variable)
    result = deployment.run("verify")
    assert result.returncode == 0, result.stderr


def test_changed_parameters_and_what_if_require_new_approval(deployment: Deployment) -> None:
    deployment.approve(deployment.review()["binding"])
    deployment.env["POSTGRES_ADMIN_PASSWORD"] = "different-dummy-password"
    assert deployment.run("publish").returncode != 0
    deployment.env["POSTGRES_ADMIN_PASSWORD"] = "dummy-private-password"
    deployment.env["STUB_WHAT_IF"] = '{"changes": []}'
    assert deployment.run("publish").returncode != 0
    assert not any(call["args"][:2] == ["acr", "build"] for call in deployment.calls("az"))


def test_rollback_requires_prior_release_and_never_builds(deployment: Deployment) -> None:
    deployment.verification()
    assert deployment.run("rollback").returncode != 0
    deployment.env["PREVIOUS_RELEASE_APPROVAL_FILE"] = deployment.env["RELEASE_APPROVAL_FILE"]
    binding = deployment.review("rollback")["binding"]
    deployment.approve(binding)
    previous = json.loads(Path(deployment.env["PREVIOUS_RELEASE_APPROVAL_FILE"]).read_text())
    deployment.env["PREVIOUS_RELEASE_APPROVAL_FILE"] = deployment.write_json(
        "previous.json", previous
    )
    deployment.approve(
        binding | {"revision": REVISION, "endpoint": "https://app.invalid"}, release=True
    )
    result = deployment.run("rollback")
    assert result.returncode == 0, result.stderr
    assert not any(call["args"][:2] == ["acr", "build"] for call in deployment.calls("az"))

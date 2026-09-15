"""OAuth protected-resource metadata for the MCP resource."""

from fastapi import APIRouter
from pydantic import AnyHttpUrl, AnyUrl, BaseModel, ConfigDict

from ask_my_human.config import Settings


class OAuthProtectedResourceMetadata(BaseModel):
    model_config = ConfigDict(url_preserve_empty_path=True)

    resource: AnyUrl
    authorization_servers: list[AnyHttpUrl]
    scopes_supported: list[str]
    bearer_methods_supported: list[str] = ["header"]


def create_oauth_metadata_router(settings: Settings) -> APIRouter:
    resource = AnyUrl(f"api://{settings.entra_client_id}")
    metadata = OAuthProtectedResourceMetadata(
        resource=resource,
        authorization_servers=[
            AnyHttpUrl(f"https://login.microsoftonline.com/{settings.entra_tenant_id}/v2.0")
        ],
        scopes_supported=[f"{resource}/.default"],
    )
    router = APIRouter()

    @router.get(
        "/.well-known/oauth-protected-resource",
        response_model=OAuthProtectedResourceMetadata,
    )
    async def oauth_protected_resource_metadata() -> OAuthProtectedResourceMetadata:
        return metadata

    return router

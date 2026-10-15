from ninja import NinjaAPI

from parsifal.api import errors
from parsifal.api.auth import API_AUTH
from parsifal.api.v1.routers import accounts, analytics, articles, extraction, protocol, quality, reviews

api = NinjaAPI(
    title="Parsifal API",
    version="1",
    description=(
        "JSON API covering the whole systematic review workflow: protocol, sources, study import and "
        "selection, quality assessment, data extraction, analytics and exports. Authenticate with "
        "`Authorization: Bearer <token>` (tokens are created in Settings → API tokens) or with the browser session."
    ),
    auth=API_AUTH,
    urls_namespace="api-v1",
    docs_url="/docs",
    openapi_url="/openapi.json",
)

errors.register(api)

api.add_router("", accounts.router)
api.add_router("", reviews.router)
api.add_router("", protocol.router)
api.add_router("", quality.router)
api.add_router("", extraction.router)
api.add_router("", articles.router)
api.add_router("", analytics.router)

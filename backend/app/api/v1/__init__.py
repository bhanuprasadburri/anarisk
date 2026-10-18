from fastapi import APIRouter

from app.api.v1 import (
    assistant, audit, auth, brands, cases, collection, dashboard, detection, entities, evidence, graph, integrations,
    monitoring, notifications, reports, tools, users,
)

api_router = APIRouter()
for module in (
    auth, users, brands, collection, entities, evidence, detection, graph, cases, dashboard, audit,
    notifications, integrations, monitoring, reports, tools, assistant,
):
    api_router.include_router(module.router)

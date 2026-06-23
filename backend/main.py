from __future__ import annotations

from fastapi import FastAPI

from app.api.v1 import assets, evals, hot_topics, sources, workflows
from app.core.observability import configure_observability


def create_app():
    configure_observability()
    app = FastAPI(title="Wemedia Agent")
    for module in (workflows, assets, sources, hot_topics, evals):
        app.include_router(module.router, prefix="/api/v1/media-agent")
    return app


app = create_app()

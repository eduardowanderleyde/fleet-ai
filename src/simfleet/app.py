"""Aplicação HTTP do SimFleet."""

from fastapi import FastAPI


def create_app() -> FastAPI:
    app = FastAPI(title="SimFleet")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app

"""Aplicação HTTP do Fleet AI."""

from fastapi import FastAPI


def create_app() -> FastAPI:
    app = FastAPI(title="Fleet AI")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app

# Imagens do Fleet AI e do SimFleet (ticket 12): dois alvos que compartilham a
# construção. Só o ambiente pronto vai para a imagem final; sem ferramentas de
# desenvolvimento, sem testes, sem chave de API.
#
#   docker build --target fleet-ai -t fleet-ai .
#   docker build --target simfleet -t simfleet .

ARG PYTHON_IMAGE=python:3.12-slim-bookworm

FROM ghcr.io/astral-sh/uv:0.13.6 AS uv

FROM ${PYTHON_IMAGE} AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /src
# Dependências primeiro, pelo lockfile, para reaproveitar a camada entre builds.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
# O pacote entra instalado (não editável), com a interface web (fleet_ai/web) e
# os cenários do SimFleet junto do código.
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

FROM ${PYTHON_IMAGE} AS runtime
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin fleet
COPY --from=build /app/.venv /app/.venv
WORKDIR /app
USER 10001

# O bind 0.0.0.0 é dentro do container; o Compose publica só em 127.0.0.1.
FROM runtime AS simfleet
EXPOSE 8001
CMD ["uvicorn", "simfleet.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8001", \
     "--no-proxy-headers", "--no-server-header", "--timeout-graceful-shutdown", "10"]

FROM runtime AS fleet-ai
EXPOSE 8000
CMD ["uvicorn", "fleet_ai.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", \
     "--no-proxy-headers", "--no-server-header", "--timeout-graceful-shutdown", "10"]

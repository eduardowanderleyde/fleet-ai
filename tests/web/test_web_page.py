"""Página da interface web: cabeçalhos e verificações estáticas (SPEC-003, ticket 01)."""

import re
from pathlib import Path

import pytest

import fleet_ai
from tests.fleet_ai_client import mission_stack

pytestmark = pytest.mark.anyio

WEB = Path(fleet_ai.__file__).parent / "web"
CSP = (
    "default-src 'self'; img-src 'self'; script-src 'self'; style-src 'self'; "
    "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)


async def test_index_is_served_with_a_strict_content_security_policy() -> None:
    async with mission_stack() as stack:
        page = await stack.api.get("/")
        script = await stack.api.get("/static/app.js")
        style = await stack.api.get("/static/app.css")

    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/html")
    assert "Fleet AI" in page.text
    for response in (page, script, style):
        assert response.status_code == 200
        assert response.headers["content-security-policy"] == CSP
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["referrer-policy"] == "no-referrer"
    assert "javascript" in script.headers["content-type"]
    assert style.headers["content-type"].startswith("text/css")


async def test_api_responses_carry_the_security_headers() -> None:
    async with mission_stack() as stack:
        response = await stack.api.get("/health/live")

    assert response.headers["content-security-policy"] == CSP
    assert response.headers["x-content-type-options"] == "nosniff"


def web_files() -> list[Path]:
    files = sorted(WEB.iterdir())
    assert {f.name for f in files} >= {"index.html", "app.js", "app.css"}
    return files


def test_web_assets_load_nothing_from_other_origins() -> None:
    for path in web_files():
        text = path.read_text()
        assert not re.search(r"https?://", text), path.name
        assert not re.search(r"""["'(=]\s*//""", text), path.name  # URL sem esquema
        assert "@import" not in text, path.name


def test_page_has_no_inline_script_style_or_handlers() -> None:
    html = (WEB / "index.html").read_text()
    assert re.findall(r"<script\b[^>]*>", html) == ['<script type="module" src="/static/app.js">']
    assert "<style" not in html
    assert not re.search(r"\sstyle\s*=", html)
    assert not re.search(r"\son[a-z]+\s*=", html)


BANNED = (
    "innerHTML",
    "outerHTML",
    "insertAdjacentHTML",
    "document.write",
    "eval(",
    "new Function",
    'setTimeout("',
    'setInterval("',
)


def test_web_script_never_renders_api_text_as_html() -> None:
    script = (WEB / "app.js").read_text()
    for token in BANNED:
        assert token not in script, token
    assert "textContent" in script

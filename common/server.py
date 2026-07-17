"""Shared root landing page + lifespan helpers for the FastAPI services.

Without a root route, opening a service in the browser shows FastAPI's bare
`{"detail":"Not Found"}`. add_landing() gives every service a clean, on-brand
HTML page (editorial matte: bone background, terracotta accent) with links to
Swagger (`/docs`) and the health check.

make_lifespan() wraps an async startup coroutine so services use FastAPI's
modern lifespan API instead of the deprecated `@app.on_event("startup")`.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

_LANDING = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{name}</title>
<style>
  :root {{--bg:#f4f1ea;--ink:#2b2b2b;--accent:#b5562f;--line:#d8d2c4}}
  * {{box-sizing:border-box}}
  body {{margin:0;min-height:100vh;display:grid;place-items:center;
        background:var(--bg);color:var(--ink);
        font:15px/1.6 -apple-system,Inter,"Segoe UI",Roboto,sans-serif}}
  .card {{background:#fff;border:1px solid var(--line);border-radius:14px;
         padding:34px 40px;max-width:540px;
         box-shadow:0 12px 34px rgba(0,0,0,.06)}}
  .tag {{display:inline-block;font:600 12px Inter,sans-serif;letter-spacing:.04em;
        color:var(--accent);border:1px solid var(--accent);
        border-radius:999px;padding:2px 11px;margin-bottom:14px}}
  h1 {{margin:0 0 6px;font-size:23px;letter-spacing:-.02em}}
  p {{margin:0 0 18px;color:#5a5750}}
  ul {{margin:0;padding-left:18px}}
  li {{margin:5px 0}}
  a {{color:var(--accent);text-decoration:none;border-bottom:1px solid var(--accent)}}
  code {{background:#f4f1ea;padding:1px 6px;border-radius:6px;font-size:13px}}
</style>
</head>
<body>
  <div class="card">
    <span class="tag">AI PR Reviewer</span>
    <h1>{name}</h1>
    <p>{desc}</p>
    <ul>
      <li><a href="/docs">Interactive API docs &rarr; <code>/docs</code></a></li>
      <li><a href="/health">Health check &rarr; <code>/health</code></a></li>
    </ul>
  </div>
</body>
</html>"""


def add_landing(app: FastAPI, name: str, description: str) -> None:
    """Attach a branded `/` landing page to a FastAPI app."""
    html = _LANDING.format(name=name, desc=description)

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def _root() -> HTMLResponse:  # noqa: B008
        return HTMLResponse(html)


def make_lifespan(on_startup: "callable[[], object]") -> "callable[[], object]":
    """Wrap an async startup coroutine into a FastAPI lifespan context manager.

    Usage::

        app = FastAPI(lifespan=make_lifespan(_startup))

    where ``_startup`` is an ``async def`` run once at startup. This replaces
    the deprecated ``@app.on_event("startup")`` hook.
    """

    @asynccontextmanager
    async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
        await on_startup()
        yield

    return _lifespan

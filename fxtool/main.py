"""FX conversion tool for an agent runtime.

One endpoint, GET /tools/convert, backed by the ECB rates published at
frankfurter.dev. The upstream base URL is configuration, not code.
"""

from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(title="fx-tool", version="1.0")


@app.get("/health")
async def health() -> dict:
    return {"ok": True}

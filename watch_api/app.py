import os
import sys

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles


if __package__ in {None, ""}:
    sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from watch_api.routes.watch_card_routes import router as watch_card_router
from watch_api.db import DatabaseConnectionError


# The FastAPI app stays intentionally small: all card logic lives in routes and services.
app = FastAPI(
    title="Watch Card API",
    version="0.1.0",
    description="Read-only mini API for smartwatch cards.",
)

app.include_router(watch_card_router)


@app.get("/health")
def health() -> dict[str, str]:
    # Used by smoke checks and uptime probes before hitting database-backed endpoints.
    return {"status": "ok"}


@app.exception_handler(DatabaseConnectionError)
def database_connection_exception_handler(_, exc: DatabaseConnectionError) -> JSONResponse:
    # Keep database failures readable for the UI and scripts instead of returning a stack trace.
    return JSONResponse(status_code=503, content={"detail": str(exc)})


# The static demo is served by the same app so the project can be tested without a frontend build step.
app.mount("/", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static"), html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("watch_api.app:app", host="127.0.0.1", port=8000, reload=True)

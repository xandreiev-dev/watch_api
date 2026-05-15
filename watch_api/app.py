import os
import sys

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles


if __package__ in {None, ""}:
    sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from watch_api.routes.watch_card_routes import router as watch_card_router
from watch_api.db import DatabaseConnectionError


app = FastAPI(
    title="Watch Card API",
    version="0.1.0",
    description="Read-only mini API for smartwatch cards.",
)

app.include_router(watch_card_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.exception_handler(DatabaseConnectionError)
def database_connection_exception_handler(_, exc: DatabaseConnectionError) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": str(exc)})


app.mount("/", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static"), html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("watch_api.app:app", host="127.0.0.1", port=8000, reload=True)

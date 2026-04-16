import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import settings, system, workspaces
from app.db import init_db
from app.services import background


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield
    background.shutdown()


app = FastAPI(
    title="cancerstudio",
    description="Backend API for the mRNA cancer vaccine design pipeline",
    version="0.1.0",
    lifespan=lifespan,
)

configured_origins = [
    origin.strip().rstrip("/")
    for origin in os.getenv("CORS_ALLOW_ORIGINS", "http://localhost:3000").split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=configured_origins,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(workspaces.router, prefix="/api/workspaces", tags=["workspaces"])
app.include_router(system.router)
app.include_router(settings.router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "cancerstudio"}

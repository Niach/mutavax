import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.api import pipeline, workspaces
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

app.include_router(pipeline.router, prefix="/api/pipeline", tags=["pipeline"])
app.include_router(workspaces.router, prefix="/api/workspaces", tags=["workspaces"])


@app.get("/health")
async def health():
    return {"status": "ok", "service": "cancerstudio"}


# WebSocket for real-time job progress
connected_clients: list[WebSocket] = []


@app.websocket("/ws/jobs")
async def job_progress_ws(websocket: WebSocket):
    await websocket.accept()
    connected_clients.append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        connected_clients.remove(websocket)


async def broadcast_job_update(job_id: str, status: str, progress: float):
    message = {"job_id": job_id, "status": status, "progress": progress}
    for client in connected_clients:
        await client.send_json(message)

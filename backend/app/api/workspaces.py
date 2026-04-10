from fastapi import APIRouter, HTTPException, Request, Response, status

from app.models.schemas import (
    ActiveStageUpdateRequest,
    UploadSessionCreateRequest,
    UploadSessionFileResponse,
    UploadSessionPartResponse,
    UploadSessionResponse,
    WorkspaceCreateRequest,
    WorkspaceResponse,
)
from app.services.workspace_store import (
    commit_upload_session,
    complete_upload_session_file,
    create_upload_session,
    create_workspace,
    list_upload_sessions,
    list_workspaces,
    load_workspace,
    update_workspace_active_stage,
    upload_session_part,
)

router = APIRouter()


@router.get("/", response_model=list[WorkspaceResponse])
async def get_workspaces():
    return list_workspaces()


@router.post(
    "/", response_model=WorkspaceResponse, status_code=status.HTTP_201_CREATED
)
async def create_workspace_route(request: WorkspaceCreateRequest):
    try:
        return create_workspace(request)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/{workspace_id}", response_model=WorkspaceResponse)
async def get_workspace(workspace_id: str):
    try:
        return load_workspace(workspace_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get(
    "/{workspace_id}/ingestion/sessions",
    response_model=list[UploadSessionResponse],
)
async def get_upload_sessions(workspace_id: str):
    try:
        return list_upload_sessions(workspace_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post(
    "/{workspace_id}/ingestion/sessions",
    response_model=UploadSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_upload_session_route(
    workspace_id: str, request: UploadSessionCreateRequest
):
    try:
        return create_upload_session(workspace_id, request)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.put(
    "/{workspace_id}/ingestion/sessions/{session_id}/files/{file_id}/parts/{part_number}",
    response_model=UploadSessionPartResponse,
)
async def upload_session_part_route(
    workspace_id: str,
    session_id: str,
    file_id: str,
    part_number: int,
    request: Request,
):
    try:
        payload = await request.body()
        return upload_session_part(workspace_id, session_id, file_id, part_number, payload)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post(
    "/{workspace_id}/ingestion/sessions/{session_id}/files/{file_id}/complete",
    response_model=UploadSessionFileResponse,
)
async def complete_upload_session_file_route(
    workspace_id: str,
    session_id: str,
    file_id: str,
):
    try:
        return complete_upload_session_file(workspace_id, session_id, file_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post(
    "/{workspace_id}/ingestion/sessions/{session_id}/commit",
    response_model=WorkspaceResponse,
)
async def commit_upload_session_route(
    workspace_id: str,
    session_id: str,
):
    try:
        return commit_upload_session(workspace_id, session_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.patch("/{workspace_id}/active-stage", response_model=WorkspaceResponse)
async def update_active_stage(
    workspace_id: str, request: ActiveStageUpdateRequest
):
    try:
        return update_workspace_active_stage(workspace_id, request)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error

from fastapi import APIRouter, Request

from app.core.shutdown_tasks import finish_thread, shutdown_tasks
from app.services.speech.jobs import speech_jobs

router = APIRouter(prefix='/projects/{project_id}/conversations/{session_id}/recordings', tags=['speech'])


@router.post('')
@shutdown_tasks.request
async def create_recording(project_id: str, session_id: str):
    return await finish_thread(speech_jobs.create, project_id, session_id)


async def directory(project_id: str, session_id: str, job_id: str):
    return await finish_thread(speech_jobs.directory, project_id, session_id, job_id)


@router.put('/{job_id}/audio')
@shutdown_tasks.request
async def upload_recording(project_id: str, session_id: str, job_id: str, request: Request):
    root = await directory(project_id, session_id, job_id)
    return await speech_jobs.upload(root, request.stream(), request.headers.get('content-type', ''))


@router.post('/{job_id}/recognize')
@shutdown_tasks.request
async def recognize_recording(project_id: str, session_id: str, job_id: str):
    return speech_jobs.start(await directory(project_id, session_id, job_id))


@router.get('/{job_id}')
async def recording_status(project_id: str, session_id: str, job_id: str):
    return speech_jobs.status(await directory(project_id, session_id, job_id))


@router.delete('/{job_id}')
async def cancel_recording(project_id: str, session_id: str, job_id: str):
    return await speech_jobs.cancel(await directory(project_id, session_id, job_id))

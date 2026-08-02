from fastapi import APIRouter

from app.api.routes.project.conversation_exports import router as conversation_exports_router
from app.api.routes.project.conversations import router as project_conversations_router
from app.api.routes.project.core import router as project_core_router
from app.api.routes.project.database import router as project_database_router
from app.api.routes.project.files import router as project_files_router
from app.api.routes.project.memory import router as project_memory_router
from app.api.routes.project.market import router as project_market_router
from app.api.routes.project.knowledge_market import router as knowledge_market_router
from app.api.routes.project.experience_market import router as experience_market_router
from app.api.routes.project.workspace import router as project_workspace_router

router = APIRouter()
router.include_router(project_core_router)
router.include_router(project_market_router)
router.include_router(knowledge_market_router)
router.include_router(experience_market_router)
router.include_router(project_files_router)
router.include_router(project_database_router)
router.include_router(project_workspace_router)
router.include_router(project_conversations_router)
router.include_router(conversation_exports_router)
router.include_router(project_memory_router)

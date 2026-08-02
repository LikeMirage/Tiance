from fastapi import APIRouter

from .catalog import router as tool_catalog_router
from .tool_dependencies import router as tool_dependencies_router
from .tool_call_records import router as tool_call_records_router
from .tool_folder_files import router as tool_folder_files_router
from .toolsets import router as toolsets_router
from .tool_market import router as tool_market_router

router = APIRouter()
router.include_router(tool_catalog_router)
router.include_router(toolsets_router)
router.include_router(tool_folder_files_router)
router.include_router(tool_dependencies_router)
router.include_router(tool_call_records_router)
router.include_router(tool_market_router)

__all__ = ["router"]

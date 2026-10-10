from pydantic import BaseModel


class DesktopExitPreparationResponse(BaseModel):
    ready: bool
    pending_tasks: int

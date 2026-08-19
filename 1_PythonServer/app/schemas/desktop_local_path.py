from pydantic import BaseModel, Field


class DesktopLocalPathRequest(BaseModel):
    path: str = Field(min_length=1)

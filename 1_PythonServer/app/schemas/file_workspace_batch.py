from pydantic import BaseModel, Field
from app.domain.file_workspace import TextFileUpdate


class TextFileUpdateRequest(BaseModel):
    path: str
    content: str
    expected_mtime_ms: int | None = None


class TextFilesSaveRequest(BaseModel):
    files: list[TextFileUpdateRequest] = Field(min_length=1)

    def updates(self) -> list[TextFileUpdate]:
        return [TextFileUpdate(**item.model_dump()) for item in self.files]

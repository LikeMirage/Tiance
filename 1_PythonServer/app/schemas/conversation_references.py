from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, RootModel, model_validator


class _ConversationReferenceBase(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class ConversationFileReference(_ConversationReferenceBase):
    display_path: str = Field(alias="displayPath")
    file_name: str = Field(alias="fileName")
    file_path: str = Field(alias="filePath")
    id: str
    kind: Literal["file", "folder"]
    project_id: str | None = Field(default=None, alias="projectId")
    source: Literal["external_path", "project_file"]

    @model_validator(mode="after")
    def require_project_id_for_project_file(self) -> Self:
        if self.source == "project_file" and not self.project_id:
            raise ValueError("projectId is required for project_file references")
        return self


class ConversationImageReference(_ConversationReferenceBase):
    display_path: str = Field(alias="displayPath")
    file_name: str = Field(alias="fileName")
    file_path: str = Field(alias="filePath")
    image_path: str = Field(alias="imagePath")
    mime_type: str = Field(alias="mimeType")
    cells: list[list[str]] | None = None
    page_number: int | None = Field(default=None, alias="pageNumber", ge=1)
    project_id: str | None = Field(default=None, alias="projectId")
    range_address: str | None = Field(default=None, alias="rangeAddress")
    size_bytes: int = Field(alias="sizeBytes", ge=0)
    sheet_name: str | None = Field(default=None, alias="sheetName")
    slide_number: int | None = Field(default=None, alias="slideNumber", ge=1)
    source: Literal["pdf_page", "ppt_slide", "xlsx_range"]
    source_display_path: str = Field(alias="sourceDisplayPath")
    source_file_name: str = Field(alias="sourceFileName")
    source_file_path: str = Field(alias="sourceFilePath")
    id: str


class ConversationWordTextPosition(_ConversationReferenceBase):
    cell_paragraph_index: int | None = Field(default=None, alias="cellParagraphIndex", ge=1)
    character_offset: int = Field(alias="characterOffset", ge=0)
    column_index: int | None = Field(default=None, alias="columnIndex", ge=1)
    container: Literal["body", "table", "header", "footer", "unknown"]
    page_number: int | None = Field(default=None, alias="pageNumber", ge=1)
    paragraph_index: int | None = Field(default=None, alias="paragraphIndex", ge=1)
    row_index: int | None = Field(default=None, alias="rowIndex", ge=1)
    table_index: int | None = Field(default=None, alias="tableIndex", ge=1)


class ConversationWordTextLocation(_ConversationReferenceBase):
    end: ConversationWordTextPosition
    kind: Literal["word_range"]
    nearest_heading: str | None = Field(default=None, alias="nearestHeading", max_length=500)
    prefix: str | None = Field(default=None, max_length=500)
    start: ConversationWordTextPosition
    suffix: str | None = Field(default=None, max_length=500)


class ConversationTextReference(_ConversationReferenceBase):
    content: str
    content_markdown: str | None = Field(default=None, alias="contentMarkdown")
    display_path: str = Field(alias="displayPath")
    document_fingerprint: str | None = Field(
        default=None,
        alias="documentFingerprint",
        pattern=r"^sha256:[0-9a-f]{64}$",
    )
    end_line: int | None = Field(default=None, alias="endLine", ge=1)
    file_name: str = Field(alias="fileName")
    file_path: str = Field(alias="filePath")
    location: ConversationWordTextLocation | None = None
    project_id: str | None = Field(default=None, alias="projectId")
    source: Literal[
        "source",
        "markdown_preview",
        "markdown_visual",
        "pdf",
        "office",
    ]
    start_line: int | None = Field(default=None, alias="startLine", ge=1)
    id: str


class ConversationFileReferenceItem(_ConversationReferenceBase):
    type: Literal["file"]
    reference: ConversationFileReference


class ConversationImageReferenceItem(_ConversationReferenceBase):
    type: Literal["image"]
    reference: ConversationImageReference


class ConversationTextReferenceItem(_ConversationReferenceBase):
    type: Literal["text"]
    reference: ConversationTextReference


ConversationReference = Annotated[
    ConversationFileReferenceItem
    | ConversationImageReferenceItem
    | ConversationTextReferenceItem,
    Field(discriminator="type"),
]


class ConversationReferences(RootModel[list[ConversationReference]]):
    root: list[ConversationReference] = Field(default_factory=list)

    def to_payload(self) -> list[dict]:
        return self.model_dump(by_alias=True, exclude_none=True)

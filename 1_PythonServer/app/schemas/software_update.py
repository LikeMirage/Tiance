from pydantic import BaseModel, ConfigDict, Field


class SoftwareUpdateCheckResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    current_version: str = Field(alias="currentVersion")
    latest_version: str = Field(alias="latestVersion")
    update_available: bool = Field(alias="updateAvailable")
    release_name: str = Field(alias="releaseName")
    release_notes: str = Field(alias="releaseNotes")
    published_at: str | None = Field(default=None, alias="publishedAt")
    download_size: int | None = Field(default=None, alias="downloadSize")
    source_checkout: bool = Field(alias="sourceCheckout")


class SoftwareUpdateDownloadResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    version: str
    stage_path: str = Field(alias="stagePath")
    package_size: int = Field(alias="packageSize")

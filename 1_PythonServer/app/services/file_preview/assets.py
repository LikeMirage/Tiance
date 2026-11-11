import mimetypes

from app.core.errors import BadRequestError


def asset_media_type(file_path) -> str:
    media_type, _ = mimetypes.guess_type(str(file_path))
    office_media_types = {
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".xls": "application/vnd.ms-excel",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    }
    extension = file_path.suffix.lower()
    if extension in office_media_types:
        return media_type or office_media_types[extension]
    if not media_type or (
        media_type != "application/pdf"
        and not media_type.startswith(("image/", "video/"))
    ):
        raise BadRequestError("仅支持读取图片、视频、PDF 或 Office 资源。")
    return media_type

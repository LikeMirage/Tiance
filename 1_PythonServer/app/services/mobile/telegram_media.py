"""Map Telegram's downloadable message variants to the ordinary file intake."""
import mimetypes

from .telegram_transport import safe_filename


def message_file(message):
    for kind, fallback in (
        ('document', '.bin'), ('audio', '.mp3'), ('voice', '.ogg'),
        ('video', '.mp4'), ('video_note', '.mp4'), ('animation', '.mp4'),
    ):
        media = message.get(kind)
        if not isinstance(media, dict) or not media.get('file_id'):
            continue
        name = media.get('file_name')
        if not name:
            mime = str(media.get('mime_type') or '').split(';')[0].strip().lower()
            suffix = {'audio/ogg': '.ogg', 'audio/mpeg': '.mp3', 'audio/mp4': '.m4a',
                      'video/mp4': '.mp4', 'image/gif': '.gif'}.get(mime)
            suffix = suffix or (mimetypes.guess_extension(mime) if mime else None) or fallback
            name = f"{kind}_{message['message_id']}{suffix}"
        return dict(media, file_name=safe_filename(name))
    if message.get('photo'):
        return dict(message['photo'][-1], file_name=f"photo_{message['message_id']}.jpg")
    return None

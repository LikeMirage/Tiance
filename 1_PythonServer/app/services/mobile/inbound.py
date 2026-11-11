"""Platform adapters translate wire messages once; the runtime owns delivery."""
from .telegram_media import message_file


def telegram_event(update):
    callback = update.get('callback_query')
    message = callback.get('message', {}) if callback else update.get('message', {})
    user = callback.get('from', {}) if callback else message.get('from', {})
    chat = message.get('chat', {})
    if not user.get('id') or chat.get('type') != 'private' or user.get('is_bot'):
        return None
    media = message_file(message)
    return dict(id=str(update['update_id']), user_id=user['id'], chat_id=chat['id'],
                name=' '.join(filter(None, [user.get('first_name'), user.get('last_name')])),
                # A caption alone must never submit a task for unsupported media.
                username=user.get('username'), text=message.get('text', message.get('caption', '') if media else ''),
                media=[media] if media else [], album=bool(message.get('media_group_id')),
                callback=callback.get('data') if callback else None,
                callback_id=callback.get('id') if callback else None,
                reply_id=(message.get('reply_to_message') or {}).get('message_id'))

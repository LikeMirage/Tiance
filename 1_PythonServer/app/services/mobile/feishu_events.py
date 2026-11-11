"""Translate Feishu private messages and interactive card actions."""
import json


def normalize_event(payload):
    header, event = payload.get('header', {}), payload.get('event', {})
    if header.get('event_type') == 'card.action.trigger':
        operator, context = event.get('operator', {}), event.get('context', {})
        value = event.get('action', {}).get('value', {})
        if not operator.get('open_id') or not context.get('open_chat_id') or not value.get('tiance'):
            return None
        return dict(id=header['event_id'], user_id=operator['open_id'], chat_id=context['open_chat_id'],
                    callback=value['tiance'], text='', media=[])
    if header.get('event_type') != 'im.message.receive_v1':
        return None
    message, sender = event.get('message', {}), event.get('sender', {})
    if message.get('chat_type') != 'p2p' or sender.get('sender_type') != 'user':
        return None
    content = message.get('content', '{}')
    content = json.loads(content) if isinstance(content, str) else content
    kind, media, text = message.get('message_type'), [], ''
    if kind == 'text':
        text = content.get('text', '')
    elif kind in {'image', 'file', 'audio', 'media'}:
        key = content.get('image_key') if kind == 'image' else content.get('file_key')
        if key:
            suffix = {'image': '.png', 'audio': '.opus', 'media': '.mp4', 'file': ''}[kind]
            media.append(dict(file_key=key, message_id=message['message_id'],
                              type='image' if kind == 'image' else 'file',
                              file_name=content.get('file_name') or f"{message['message_id']}{suffix}"))
    elif kind == 'post':
        # Rich text contains ordinary text and image references, no HTML scraping.
        blocks = content if 'content' in content else next(iter(content.values()), {})
        text = blocks.get('title', '') + '\n'
        for row in blocks.get('content', []):
            for item in row:
                text += item.get('text', '')
                if item.get('tag') == 'img' and item.get('image_key'):
                    media.append(dict(file_key=item['image_key'], message_id=message['message_id'],
                                      type='image', file_name=item['image_key'] + '.png'))
            text += '\n'
    return dict(id=header.get('event_id') or message['message_id'],
                user_id=sender['sender_id']['open_id'], chat_id=message['chat_id'],
                text=text.strip(), media=media, reply_id=message.get('parent_id'))

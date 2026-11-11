"""Read ordinary conversation history; no model invocation or selection changes."""
from app.services.project import get_project_conversation_service
from .context import resolve_target


def recent_history_text(target):
    resolve_target(target)
    turns = get_project_conversation_service().recent_history(
        target['project_id'], target['session_id'], limit=5,
    )
    if not turns:
        return '此会话还没有对话记录。'
    blocks = [f'最近 {len(turns)} 轮对话（从早到晚）']
    for index, turn in enumerate(turns, 1):
        blocks.extend([f'—— 第 {index}/{len(turns)} 轮 ——',
                       '用户：\n' + (turn['user_content'] or '（无文字）')])
        for item in turn['references']:
            ref = item.get('reference', item)
            name = ref.get('fileName') or ref.get('title') or ref.get('name') or '引用'
            path = ref.get('displayPath') or ref.get('filePath') or ref.get('path') or ''
            blocks.append(f'引用：{name}' + (f'\n{path}' if path else ''))
        status = turn['status']
        answer = turn['assistant_content']
        if answer:
            label = 'AI（尚未完成）' if status == 'running' else 'AI'
            blocks.append(label + '：\n' + answer)
        else:
            blocks.append('AI：' + ('仍在处理中，尚无正式回复。' if status == 'running' else '没有正式回复。'))
        if status == 'cancelled':
            blocks.append('状态：已暂停。')
        elif status == 'error':
            blocks.append('状态：执行失败。')
        blocks.extend('错误：' + error for error in turn['errors'])
    return '\n\n'.join(blocks)

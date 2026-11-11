"""Feishu card layout: content rows, compact operations, then quiet navigation."""


def plain(text):
    return {'tag': 'plain_text', 'content': text}


def note(text):
    return {'tag': 'note', 'elements': [plain(text)]}


def button_element(button, *, label=None, tone=None, fill=False):
    return {
        'tag': 'button', 'text': plain(label or button['text']),
        'type': tone or button.get('presentation', {}).get('tone', 'default'),
        'size': 'small', 'width': 'fill' if fill else 'default',
        'value': {'tiance': button['callback_data']},
    }


def columns(items, *, weighted=True):
    return {
        'tag': 'column_set', 'flex_mode': 'none', 'horizontal_spacing': 'small',
        'columns': [dict(
            tag='column', width='weighted' if weighted or index == 0 else 'auto',
            **({'weight': 1} if weighted or index == 0 else {}),
            vertical_align='center', elements=[item],
        ) for index, item in enumerate(items)],
    }


def entry_row(button):
    view = button['presentation']
    label = button['text'] + (' · 当前' if view.get('current') else '')
    return columns([
        {'tag': 'div', 'text': plain(label)},
        button_element(button, label=view['label'], tone='primary_text'),
    ], weighted=False)


def toolbar(buttons, *, quiet=False):
    for start in range(0, len(buttons), 2):
        yield columns([button_element(button, tone='text' if quiet else None, fill=True)
                       for button in buttons[start:start + 2]])


def build_card(text, rows, *, header=''):
    groups = {role: [] for role in ('entry', 'pagination', 'operation', 'navigation')}
    for row in rows:
        for button in row:
            role = button.get('presentation', {}).get('role', 'operation')
            groups[role].append(button)

    elements = [note(header)] if header else []
    elements.append({'tag': 'div', 'text': plain(text)})
    elements.extend(entry_row(button) for button in groups['entry'])
    elements.extend(toolbar(groups['pagination'], quiet=True))
    if groups['operation']:
        elements.extend([{'tag': 'hr'}, note('操作')])
        elements.extend(toolbar(groups['operation']))
    if groups['navigation']:
        elements.extend([{'tag': 'hr'}, note('快捷导航')])
        elements.extend(toolbar(groups['navigation'], quiet=True))
    return {'config': {'wide_screen_mode': True}, 'elements': elements}

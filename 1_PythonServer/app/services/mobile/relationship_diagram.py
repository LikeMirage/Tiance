"""Render a complete collection outline as readable PNG pages, with no graph dependency."""
from pathlib import Path
import os
from uuid import uuid4
from PIL import Image, ImageDraw, ImageFont

WIDTH = 1520
PAGE_HEIGHT = 1800
COLUMNS = [(30, 180), (240, 500), (560, 900), (960, 1490)]


def diagram_directory():
    from app.core.config import get_settings
    return get_settings().cache_data_path / 'mobile' / 'relationship-diagrams'


def diagram_font(size):
    for file in [Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts/msyh.ttc',
                 Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc')]:
        if file.is_file():
            return ImageFont.truetype(str(file), size)
    raise RuntimeError('关系图需要中文字体，未找到系统微软雅黑或 Noto Sans CJK。')


def wrapped(text, font, width):
    lines, line = [], ''
    for character in str(text):
        if character == '\n' or (line and font.getlength(line + character) > width):
            lines.append(line)
            line = ''
        if character != '\n':
            line += character
    lines.append(line)
    return lines


def outline_rows(outline):
    rows = []
    for category in outline['categories']:
        if not category['projects']:
            rows.append((category, None, None))
        for project in category['projects']:
            for session in project['sessions'] or [None]:
                rows.append((category, project, session))
    return rows


def render_diagram(outline, directory=None):
    directory = Path(directory) if directory else diagram_directory()
    directory.mkdir(parents=True, exist_ok=True)
    font = diagram_font(24)
    rows = outline_rows(outline)
    pages, page, used = [], [], 150
    for category, project, session in rows:
        labels = [category['name'], project['name'] if project else '暂无项目',
                  session['name'] if session else (project.get('error') or '暂无主会话') if project else '']
        lines = [wrapped(text, font, right-left-24) for text, (left,right) in zip(labels,COLUMNS[1:])]
        height = max(64, max(map(len, lines))*32+28)
        if page and used + height > PAGE_HEIGHT - 60:
            pages.append(page)
            page, used = [], 150
        page.append((category, project, session, lines, height))
        used += height
    pages.append(page)
    paths = []
    try:
        for number, items in enumerate(pages, 1):
            height = max(380, 190 + sum(item[-1] for item in items))
            image = Image.new('RGB', (WIDTH, height), '#f6f8fc')
            draw = ImageDraw.Draw(image)
            draw.text((30, 22), f"{outline['name']} · 分类 / 项目 / 主会话", font=diagram_font(30), fill='#172b4d')
            draw.text((30, 70), f'第 {number} / {len(pages)} 张 · 下级会话未展开', font=font, fill='#58687d')
            positions, top = [], 140
            for item in items:
                positions.append((top, top+item[-1]))
                top += item[-1]
            def box(column, center, lines):
                left, right = COLUMNS[column]
                box_height = len(lines)*32+16
                draw.rounded_rectangle((left,center-box_height/2,right,center+box_height/2),radius=8,
                                       fill='#ffffff',outline='#9db4d0',width=2)
                for index, line in enumerate(lines):
                    draw.text((left+12,center-box_height/2+8+index*32),line,font=font,fill='#172b4d')
            def edge(left_column, parent_y, child_y):
                start, end = COLUMNS[left_column][1], COLUMNS[left_column+1][0]
                middle = (start+end)/2
                draw.line([(start,parent_y),(middle,parent_y),(middle,child_y),(end,child_y)],fill='#8fa6c1',width=2)
            root_y = (140+top)/2
            box(0, root_y, wrapped(outline['name'],font,126))
            if not items:
                draw.text((240, 200),'暂无分类',font=font,fill='#58687d')
            index = 0
            while index < len(items):
                end = index+1
                while end < len(items) and items[end][0]['id'] == items[index][0]['id']:
                    end += 1
                category_y = (positions[index][0]+positions[end-1][1])/2
                edge(0,root_y,category_y)
                box(1,category_y,items[index][3][0])
                project_start = index
                while project_start < end:
                    project_end = project_start+1
                    while project_end < end and items[project_end][1] == items[project_start][1]:
                        project_end += 1
                    project_y = (positions[project_start][0]+positions[project_end-1][1])/2
                    edge(1,category_y,project_y)
                    box(2,project_y,items[project_start][3][1])
                    if items[project_start][1]:
                        for offset in range(project_start,project_end):
                            y = sum(positions[offset])/2
                            edge(2,project_y,y)
                            box(3,y,items[offset][3][2])
                    project_start = project_end
                index = end
            path = directory / f'{uuid4().hex}.png'
            image.save(path)
            image.close()
            paths.append(path)
        return paths
    except BaseException:
        for path in paths:
            path.unlink(missing_ok=True)
        raise


def remove_diagram(file):
    path = Path(file).resolve()
    if path.parent == diagram_directory().resolve() and path.suffix == '.png':
        path.unlink(missing_ok=True)

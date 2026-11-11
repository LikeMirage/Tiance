"""Channel-neutral creation/navigation snapshots; use desktop application services."""
from app.core.errors import BadRequestError, NotFoundError
from app.domain.project import ProjectKind
from app.services.application.project_creation import get_project_creation_application_service
from app.services.project import get_project_service
from .context import COLLECTIONS, session_children


def collection_kind(value):
    if value not in COLLECTIONS:
        raise BadRequestError('请先选择项目集、工具集等具体的集。')
    return ProjectKind(value)


def create_category(kind, name):
    if not name or not name.strip():
        raise BadRequestError('请输入分类名称，例如 /newcategory 工作项目。')
    return get_project_service().create_project_category(name=name, category_kind=collection_kind(kind))


def create_project(kind, category_id, name):
    kind = collection_kind(kind)
    if not name or not name.strip():
        raise BadRequestError('请输入项目名称，例如 /newproject 会议纪要。')
    category = get_project_service().get_project_category(category_id) if category_id else None
    if category is None or category.category_kind != kind:
        raise BadRequestError('请先在该集选择一个具体分类，再新建项目。')
    creator = get_project_creation_application_service()
    if kind is ProjectKind.PROVIDER:
        from app.schemas.llm.provider_catalog import ProviderCatalogCreateRequest
        from app.services.llm.provider.catalog_mutation import get_provider_catalog_mutation_service
        from app.services.llm.provider.workspace_registry import provider_project_id
        payload = ProviderCatalogCreateRequest(display_name=name, category_id=category_id)
        entry = get_provider_catalog_mutation_service().create_provider(**payload.model_dump())
        project = get_project_service().get_project(provider_project_id(entry.provider_id))
        if project is None:
            raise NotFoundError('供应商已创建，但对应工作区尚未登记，请在模型集检查。')
        creator.ensure_initial_conversation(project.project_id)
    else:
        project = creator.create_project(name=name, category_id=category_id, project_kind=kind)
    return project


def collection_outline(kind):
    """Titles/relations only. Never reads histories, prompts, file contents or usage."""
    kind = collection_kind(kind)
    service = get_project_service()
    categories = [c for c in service.list_project_categories() if c.category_kind == kind]
    projects = [p for p in service.list_projects() if p.project_kind == kind]
    groups = []
    for category in categories:
        children = []
        for project in projects:
            if project.category_id != category.category_id:
                continue
            try:
                roots = session_children(project.project_id)
                sessions = [{'id': s.session_id, 'name': s.title} for s, _ in roots]
                error = None
            except NotFoundError:
                sessions, error = [], '项目已移除，请刷新'
            children.append({'id': project.project_id, 'name': project.name, 'sessions': sessions, 'error': error})
        groups.append({'id': category.category_id, 'name': category.name, 'projects': children})
    # Show catalog inconsistencies instead of silently omitting projects.
    known = {c.category_id for c in categories}
    ungrouped = [p for p in projects if p.category_id not in known]
    if ungrouped:
        groups.append({'id': '', 'name': '分类已不存在', 'projects': [
            {'id': p.project_id, 'name': p.name, 'sessions': [
                {'id': s.session_id, 'name': s.title} for s, _ in session_children(p.project_id)], 'error': None}
            for p in ungrouped]})
    return {'name': COLLECTIONS[kind], 'categories': groups}

"""Build all current file catalogs for service fixtures, with explicit per-kind roots."""
from app.domain.project import ProjectKind
from app.repositories.project import FileProjectCatalog, ProjectRepository
from app.repositories.project.project_repository import COLLECTION_DIRECTORIES


def make_project_repository(database_path, *, file_catalogs=()):
    catalogs = {catalog.project_kind: catalog for catalog in file_catalogs}
    for kind, directory in COLLECTION_DIRECTORIES.items():
        catalogs.setdefault(kind, FileProjectCatalog(
            database_path.parent / directory, project_kind=kind,
            allow_external_roots=kind is ProjectKind.PROJECT,
        ))
    return ProjectRepository(database_path, file_catalogs=tuple(catalogs.values()))

import ctypes
import os
from pathlib import Path

import pytest

from app.core.errors import BadRequestError
from app.domain.project import ProjectKind
from app.infra import system_recycle_bin as native
from app.infra.database import ensure_database_schema
from app.infra.projects import ProjectStorage
from app.infra.projects import project_storage
from app.repositories.project import ProjectRepository
from app.repositories.project.file_project_catalog import FileProjectCatalog
from app.services.project.projects import ProjectService


@pytest.fixture(params=['sqlite', 'file'])
def services(tmp_path, request):
    database = tmp_path / 'tiance.db'
    ensure_database_schema(database)
    managed = tmp_path / 'managed'
    catalogs = (FileProjectCatalog(managed, project_kind=ProjectKind.PROJECT, allow_external_roots=True),) if request.param == 'file' else ()
    repository = ProjectRepository(database, file_catalogs=catalogs)
    storage = ProjectStorage(managed)
    return ProjectService(repository, storage), repository, storage


def make_external(tmp_path, service, category=None, name='外部项目'):
    folder = tmp_path / name
    folder.mkdir()
    (folder / 'proof.txt').write_text('keep all bytes', encoding='utf-8')
    return service.create_project(name=name, root_path=str(folder), category_id=category)


def test_external_delete_calls_system_without_private_archive(services, tmp_path, fake_system_recycle, monkeypatch):
    import shutil
    def forbidden(*args, **kwargs):
        pytest.fail('Project deletion must not copy or privately archive files')
    monkeypatch.setattr(shutil, 'move', forbidden)
    monkeypatch.setattr(shutil, 'copytree', forbidden)
    service, repository, storage = services
    project = make_external(tmp_path, service)
    service.delete_project(project.project_id, delete_files=True)
    assert repository.get_project(project.project_id) is None
    assert fake_system_recycle[0][0] == Path(project.root_path)
    assert (fake_system_recycle[0][1] / 'proof.txt').read_text() == 'keep all bytes'
    assert not (storage.projects_root / '.trash').exists()
    assert not (tmp_path / '.tiance-trash').exists()


def test_recycle_failure_keeps_files_and_registration(services, tmp_path, monkeypatch):
    service, repository, _ = services
    project = make_external(tmp_path, service)
    def blocked(path):
        raise OSError('recycle bin unavailable')
    monkeypatch.setattr(project_storage, 'recycle_path', blocked)
    with pytest.raises(BadRequestError, match='项目登记已保留'):
        service.delete_project(project.project_id, delete_files=True)
    assert repository.get_project(project.project_id) is not None
    assert (Path(project.root_path) / 'proof.txt').read_text() == 'keep all bytes'


def test_registration_failure_is_reported_without_restoring_files(services, tmp_path, fake_system_recycle, monkeypatch):
    service, repository, _ = services
    project = make_external(tmp_path, service)
    real_delete = repository.delete_project
    monkeypatch.setattr(repository, 'delete_project', lambda _: (_ for _ in ()).throw(OSError('index failed')))
    with pytest.raises(BadRequestError) as error:
        service.delete_project(project.project_id, delete_files=True)
    assert error.value.details['files_recycled'] is True
    assert not Path(project.root_path).exists()
    assert repository.get_project(project.project_id) is not None
    monkeypatch.setattr(repository, 'delete_project', real_delete)
    service.delete_project(project.project_id, delete_files=True)
    assert len(fake_system_recycle) == 1
    assert repository.get_project(project.project_id) is None


def test_remove_external_project_only_removes_registration(services, tmp_path, monkeypatch):
    service, repository, _ = services
    project = make_external(tmp_path, service)
    monkeypatch.setattr(project_storage, 'recycle_path', lambda _: pytest.fail('remove must not recycle'))
    service.delete_project(project.project_id)
    assert Path(project.root_path).is_dir()
    assert repository.get_project(project.project_id) is None


def test_category_partial_failure_keeps_remaining_projects_and_category(services, tmp_path, fake_system_recycle, monkeypatch):
    service, repository, _ = services
    category = service.create_project_category(name='批量删除')
    projects = [make_external(tmp_path, service, category.category_id, name=f'项目{i}') for i in range(3)]
    original = project_storage.recycle_path
    def fail_second(path):
        if path == Path(projects[1].root_path):
            raise OSError('folder locked')
        original(path)
    monkeypatch.setattr(project_storage, 'recycle_path', fail_second)
    with pytest.raises(BadRequestError) as error:
        service.delete_project_category(category.category_id)
    assert error.value.details['completed_project_ids'] == [projects[0].project_id]
    assert repository.get_project(projects[0].project_id) is None
    assert repository.get_project_category(category.category_id) is not None
    for project in projects[1:]:
        assert Path(project.root_path).is_dir()
        assert repository.get_project(project.project_id) is not None
    monkeypatch.setattr(project_storage, 'recycle_path', original)
    service.delete_project_category(category.category_id)
    assert len(fake_system_recycle) == 3
    assert repository.get_project_category(category.category_id) is None


def test_category_delete_does_not_remove_concurrently_added_project(services, tmp_path, fake_system_recycle, monkeypatch):
    service, repository, _ = services
    category = service.create_project_category(name='并发新增')
    make_external(tmp_path, service, category.category_id)
    delete_category = repository.delete_project_category
    added = []
    def add_before_delete(category_id):
        added.append(make_external(tmp_path, service, category_id, '刚新增的项目'))
        delete_category(category_id)
    monkeypatch.setattr(repository, 'delete_project_category', add_before_delete)
    with pytest.raises(BadRequestError, match='分类登记移除失败'):
        service.delete_project_category(category.category_id)
    assert len(fake_system_recycle) == 1
    assert repository.get_project(added[0].project_id) is not None
    assert Path(added[0].root_path).is_dir()


@pytest.mark.parametrize('target', ['drive', 'managed', 'ancestor', 'outside-as-managed'])
def test_recycle_rejects_unsafe_targets_before_system_call(tmp_path, monkeypatch, target):
    storage = ProjectStorage(tmp_path / 'managed')
    paths = {'drive': Path(tmp_path.anchor), 'managed': storage.projects_root,
        'ancestor': tmp_path, 'outside-as-managed': tmp_path / 'other'}
    monkeypatch.setattr(project_storage, 'recycle_path', lambda _: pytest.fail('unsafe target'))
    with pytest.raises(ValueError):
        storage.recycle_project_root(str(paths[target]), external=target != 'outside-as-managed')


def test_empty_creation_cleanup_does_not_delete_contents(tmp_path):
    storage = ProjectStorage(tmp_path / 'managed')
    source = storage.ensure_project_root('new-id')
    (source / 'keep.txt').write_text('keep')
    with pytest.raises(OSError):
        storage.remove_empty_project_root(str(source))
    assert (source / 'keep.txt').read_text() == 'keep'


def test_shell_progress_rejects_permanent_delete_and_reports_failures():
    sink = native._RecycleProgress()
    assert sink._pre_delete(None, 0, None) == native.E_ABORT
    assert not sink.recycled and '停止删除' in sink.error
    sink = native._RecycleProgress()
    assert sink._pre_delete(None, native.TSF_DELETE_RECYCLE_IF_POSSIBLE, None) == 0
    sink._post_delete(None, 0, None, -2147024891, None)
    assert sink.error and not sink.recycled
    sink = native._RecycleProgress()
    sink._post_delete(None, 0, None, 0, None)
    assert sink.error and not sink.recycled
    sink = native._RecycleProgress()
    sink._post_delete(None, 0, None, 2555912, 123)
    assert sink.recycled and sink.error is None


@pytest.mark.skipif(os.name != 'nt' or os.getenv('TIANCE_TEST_SYSTEM_RECYCLE_BIN') != '1',
    reason='Explicit opt-in: recycles only a uniquely named temporary test folder')
def test_native_shell_recycles_directory_with_complete_content(tmp_path, monkeypatch):
    source = (tmp_path / 'Tiance-系统回收验证').resolve()
    assert source.is_relative_to(tmp_path.resolve()) and source != tmp_path.resolve()
    source.mkdir()
    (source / 'proof.txt').write_text('native recycle test', encoding='utf-8')
    observed = []
    post = native._RecycleProgress._post_delete
    def record(self, this, flags, item, result, recycled):
        if recycled:
            name = ctypes.c_void_p()
            native._check(native._method(ctypes.c_void_p(recycled), 5, ctypes.c_uint32,
                ctypes.POINTER(ctypes.c_void_p))(recycled, 0x80058000, ctypes.byref(name)))
            try:
                observed.append(Path(ctypes.wstring_at(name)))
            finally:
                free = ctypes.WinDLL('ole32').CoTaskMemFree
                free.argtypes = [ctypes.c_void_p]
                free(name)
        return post(self, this, flags, item, result, recycled)
    monkeypatch.setattr(native._RecycleProgress, '_post_delete', record)
    native.recycle_path(source)
    assert not source.exists() and len(observed) == 1
    assert '$recycle.bin' in str(observed[0]).lower()
    assert (observed[0] / 'proof.txt').read_text(encoding='utf-8') == 'native recycle test'


@pytest.mark.skipif(os.name != 'nt' or os.getenv('TIANCE_TEST_SYSTEM_RECYCLE_BIN') != '1', reason='Native Shell opt-in')
def test_native_shell_aborts_when_recycling_is_not_offered(tmp_path, monkeypatch):
    source = (tmp_path / 'Tiance-取消删除验证').resolve()
    assert source.is_relative_to(tmp_path.resolve()) and source != tmp_path.resolve()
    source.mkdir()
    (source / 'proof.txt').write_text('untouched')
    pre = native._RecycleProgress._pre_delete
    monkeypatch.setattr(native._RecycleProgress, '_pre_delete',
        lambda self, this, flags, item: pre(self, this, flags & ~native.TSF_DELETE_RECYCLE_IF_POSSIBLE, item))
    with pytest.raises(OSError, match='停止删除'):
        native.recycle_path(source)
    assert (source / 'proof.txt').read_text() == 'untouched'

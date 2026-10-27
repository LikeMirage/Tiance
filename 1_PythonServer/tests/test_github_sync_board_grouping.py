from app.domain.github_sync import GithubSyncFile
from app.services.application.github_project_sync import build_board
from app.services.application.github_sync_snapshot import LocalSnapshot, LocalSnapshotFile


def test_board_preserves_categories_order_file_states_and_uncatalogued_projects():
    catalog = {
        "categories": [
            {"category_id": "c2", "name": "第二类", "sort_order": 2},
            {"category_id": "c1", "name": "第一类", "sort_order": 1},
            {"category_id": "empty", "name": "空分类", "sort_order": 3},
        ],
        "projects": [
            {"project_id": "p1", "name": "本地名称", "category_id": "c1", "sort_order": 1},
            {"project_id": "p10", "name": "十", "category_id": "c2", "sort_order": 2},
            {"project_id": "empty", "name": "空项目", "category_id": "c1", "sort_order": 0},
        ],
    }
    local = LocalSnapshot({
        path: LocalSnapshotFile(path=path, sha=sha, size=3, content=b"abc")
        for path, sha in {
            "catalog.json": "catalog", "root.txt": "root", "p1/same.txt": "same",
            "p1/changed.txt": "old", "p1/local.txt": "local", "p10/file.txt": "ten",
            "uncatalogued/file.txt": "uncatalogued",
        }.items()
    }, "test")
    remote = {
        path: GithubSyncFile(path=path, sha=sha, size=5)
        for path, sha in {"p1/same.txt": "same", "p1/changed.txt": "new", "p1/remote.txt": "remote"}.items()
    }
    categories, projects, changed = build_board(
        local=local, remote=remote, local_catalog=catalog,
        remote_catalog={"projects": [{"project_id": "p1", "name": "远端名称"}]},
    )
    by_id = {project["projectId"]: project for project in projects}
    assert changed == 5
    assert by_id["p1"]["name"] == "本地名称"
    assert by_id["p1"]["location"] == "both"
    assert [(row["relativePath"], row["status"]) for row in by_id["p1"]["files"]] == [
        ("changed.txt", "different"), ("local.txt", "local-only"), ("remote.txt", "remote-only"),
    ]
    assert by_id["p1"]["files"][0]["localSize"] == 3
    assert by_id["p1"]["files"][0]["remoteSize"] == 5
    assert by_id["p10"]["changedFiles"] == 1
    assert by_id["empty"]["files"] == []
    categories_by_id = {row["categoryId"]: row for row in categories}
    assert categories_by_id["c1"]["projectIds"] == ["empty", "p1"]
    assert categories_by_id["c1"]["changedFiles"] == 3
    assert categories_by_id["c2"]["projectIds"] == ["p10"]
    assert categories_by_id["empty"]["changedFiles"] == 0
    assert categories_by_id["__uncategorized__"]["projectIds"] == ["uncatalogued"]
    assert [row["categoryId"] for row in categories if row["categoryId"] != "__uncategorized__"] == ["c1", "c2", "empty"]


def test_board_scans_file_collection_once_instead_of_once_per_project():
    class CountFiles(dict):
        scans = 0
        def __iter__(self):
            self.scans += 1
            return super().__iter__()

    files = CountFiles({
        f"p{project}/f{item}.txt": LocalSnapshotFile(
            path=f"p{project}/f{item}.txt", size=1, sha="local", content=b"x",
        )
        for project in range(100) for item in range(20)
    })
    remote = CountFiles()
    _, projects, changed = build_board(
        local=LocalSnapshot(files, "test"), remote=remote, local_catalog={}, remote_catalog={},
    )
    assert len(projects) == 100
    assert changed == 2000
    assert all(project["changedFiles"] == 20 for project in projects)
    assert files.scans == remote.scans == 1

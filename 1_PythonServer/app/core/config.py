# 应用配置模块
# 从 .env 和环境变量读取运行时配置：CORS、数据库路径、项目存储路径等

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Tiance API Server"
    app_version: str = "0.3.0"
    environment: str = "development"
    log_level: str = "INFO"
    api_prefix: str = "/api"
    database_file: str = "Data/db/tiance.db"
    projects_data_dir: str = "Data/projects"
    tools_data_dir: str = "Data/tools"
    knowledge_data_dir: str = "Data/knowledge"
    experience_data_dir: str = "Data/experience"
    roles_data_dir: str = "Data/roles"
    memory_data_dir: str = "Data/memory"
    usage_data_dir: str = "Data/usage"
    themes_data_dir: str = "Data/themes"
    providers_data_dir: str = "Data/providers"
    locales_data_dir: str = "Data/locales"
    runtime_env_dir: str = "Data/runtime"
    frontend_dist_dir: str = "2_ReactWeb/dist"
    github_client_id: str = "Iv23liNTtDOlpz60vMVw"
    tool_dependency_index_url: str = "https://mirrors.aliyun.com/pypi/simple/"
    tool_dependency_install_timeout_seconds: int = 300
    allowed_origins: str = (
        "http://127.0.0.1:18100,http://localhost:18100,"
        "https://pywebview.flowrl.com"
    )
    allowed_origin_regex: str | None = None
    allow_null_origin: bool = False
    allow_file_origin: bool = False

    @property
    def cors_origins(self) -> list[str]:
        origins = [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]
        if self.allow_null_origin:
            origins.append("null")
        if self.allow_file_origin:
            origins.append("file://")
        return list(dict.fromkeys(origins))

    @property
    def cors_origin_regex(self) -> str | None:
        return self.allowed_origin_regex.strip() if self.allowed_origin_regex else None

    @property
    def app_database_file(self) -> Path:
        return self._resolve_project_path(self.database_file)

    @property
    def projects_data_path(self) -> Path:
        return self._resolve_project_path(self.projects_data_dir)

    @property
    def tools_data_path(self) -> Path:
        return self._resolve_project_path(self.tools_data_dir)

    @property
    def knowledge_data_path(self) -> Path:
        return self._resolve_project_path(self.knowledge_data_dir)

    @property
    def experience_data_path(self) -> Path:
        return self._resolve_project_path(self.experience_data_dir)

    @property
    def roles_data_path(self) -> Path:
        return self._resolve_project_path(self.roles_data_dir)

    @property
    def memory_data_path(self) -> Path:
        return self._resolve_project_path(self.memory_data_dir)

    @property
    def usage_data_path(self) -> Path:
        return self._resolve_project_path(self.usage_data_dir)

    @property
    def themes_data_path(self) -> Path:
        return self._resolve_project_path(self.themes_data_dir)

    @property
    def providers_data_path(self) -> Path:
        return self._resolve_project_path(self.providers_data_dir)

    @property
    def locales_data_path(self) -> Path:
        return self._resolve_project_path(self.locales_data_dir)

    @property
    def runtime_env_path(self) -> Path:
        return self._resolve_project_path(self.runtime_env_dir)

    @property
    def secrets_data_path(self) -> Path:
        database_parent = self.app_database_file.parent
        data_root = (
            database_parent.parent
            if database_parent.name.lower() == "db"
            else database_parent
        )
        return data_root / "secrets"

    @property
    def frontend_dist_path(self) -> Path:
        return self._resolve_project_path(self.frontend_dist_dir)

    @property
    def embedded_python_file(self) -> Path:
        return self.runtime_env_path / "python" / "py313" / (
            "python.exe" if _is_windows() else "python"
        )

    @property
    def embedded_pip_runner_file(self) -> Path:
        return self.runtime_env_path / "python" / "run_pip.py"

    @property
    def embedded_pip_site_packages_path(self) -> Path:
        return self.runtime_env_path / "python-packages" / "pip" / "py313" / "site-packages"

    def _resolve_project_path(self, raw_path: str) -> Path:
        path = Path(raw_path).expanduser()
        if path.is_absolute():
            return path
        return _find_project_root() / path


@lru_cache
def get_settings() -> Settings:
    """获取配置单例（缓存避免重复读取 .env）"""

    return Settings()


@lru_cache
def _find_project_root() -> Path:
    """向上遍历查找 .git 目录或工作区根标记来确定项目根目录"""

    current_file = Path(__file__).resolve()
    for parent in current_file.parents:
        if (parent / ".git").exists():
            return parent
        if (parent / "1_PythonServer").is_dir() and (parent / "4_文档").is_dir():
            return parent
        if parent.name == "1_PythonServer" and (parent / "pyproject.toml").is_file():
            return parent.parent
    return Path.cwd().resolve()


def _is_windows() -> bool:
    import os

    return os.name == "nt"

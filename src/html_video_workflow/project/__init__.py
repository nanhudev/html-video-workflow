"""Video Project IR, migration and on-disk storage."""
from .ir import SCHEMA_VERSION, VideoProject, validate_project
from .migrate import detect_version, load_project as load_any, migrate, needs_migration
from .store import (
    list_projects,
    load_project,
    load_project_file,
    new_project_id,
    project_dir,
    save_project,
)

__all__ = [
    "SCHEMA_VERSION",
    "VideoProject",
    "validate_project",
    "detect_version",
    "load_any",
    "migrate",
    "needs_migration",
    "list_projects",
    "load_project",
    "load_project_file",
    "new_project_id",
    "project_dir",
    "save_project",
]

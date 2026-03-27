"""
SEO Storage Utilities — centralized disk I/O for SEO module.

Enforces project directory layout:
  STORAGE_DIR/seo_projects/{project_id}/
  ├── project.json                            # SEOState serialized
  ├── data_objects/
  │   ├── seo_project_context_v1.json         # Versioned data objects
  │   └── ...
  └── jobs/
      └── {job_id}.json                       # Individual job records
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional


def ensure_project_dir(project_id: str, storage_dir: Path) -> Path:
    """Creates the three-level directory structure if it does not exist."""
    project_dir = storage_dir / "seo_projects" / project_id
    (project_dir / "data_objects").mkdir(parents=True, exist_ok=True)
    (project_dir / "jobs").mkdir(parents=True, exist_ok=True)
    return project_dir


def save_data_object(
    project_id: str,
    data_type: str,
    data: Dict[str, Any],
    version: Optional[int],
    storage_dir: Path,
) -> int:
    """Writes data_objects/{data_type}_v{version}.json. Uses atomic write.
    
    If version is not provided, auto-determines next version by scanning existing files.
    Returns the version number used.
    """
    if version is None:
        version = get_next_version(project_id, data_type, storage_dir)
    
    project_dir = ensure_project_dir(project_id, storage_dir)
    temp_path = project_dir / "data_objects" / f"{data_type}_v{version}.json.tmp"
    target_path = project_dir / "data_objects" / f"{data_type}_v{version}.json"

    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    os.replace(temp_path, target_path)
    
    cleanup_old_versions(project_id, data_type, storage_dir, keep=3)
    
    return version


def get_next_version(
    project_id: str,
    data_type: str,
    storage_dir: Path,
) -> int:
    """Determines the next version number by scanning existing files."""
    versions = list_data_object_versions(project_id, data_type, storage_dir)
    if not versions:
        return 1
    return max(versions) + 1


def load_data_object(
    project_id: str,
    data_type: str,
    version: Optional[int],
    storage_dir: Path,
) -> Optional[Dict[str, Any]]:
    """Loads the specified version, or the latest if version is None."""
    if version:
        target_path = (
            storage_dir
            / "seo_projects"
            / project_id
            / "data_objects"
            / f"{data_type}_v{version}.json"
        )
        if target_path.exists():
            with open(target_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return None

    versions = list_data_object_versions(project_id, data_type, storage_dir)
    if not versions:
        return None

    latest_version = max(versions)
    return load_data_object(project_id, data_type, latest_version, storage_dir)


def list_data_object_versions(
    project_id: str,
    data_type: str,
    storage_dir: Path,
) -> List[int]:
    """Returns sorted list of available version numbers."""
    data_objects_dir = storage_dir / "seo_projects" / project_id / "data_objects"
    if not data_objects_dir.exists():
        return []

    versions = []
    for f in data_objects_dir.glob(f"{data_type}_v*.json"):
        try:
            version_str = f.stem.split("_v")[-1]
            versions.append(int(version_str))
        except (ValueError, IndexError):
            continue

    return sorted(versions)


def cleanup_old_versions(
    project_id: str,
    data_type: str,
    storage_dir: Path,
    keep: int = 3,
) -> None:
    """Deletes all versions older than the most recent keep versions."""
    versions = list_data_object_versions(project_id, data_type, storage_dir)
    if len(versions) <= keep:
        return

    versions_to_delete = versions[:-keep]
    data_objects_dir = storage_dir / "seo_projects" / project_id / "data_objects"

    for v in versions_to_delete:
        file_path = data_objects_dir / f"{data_type}_v{v}.json"
        if file_path.exists():
            file_path.unlink()


def save_job(
    project_id: str,
    job_id: str,
    job: Dict[str, Any],
    storage_dir: Path,
) -> None:
    """Writes jobs/{job_id}.json."""
    project_dir = ensure_project_dir(project_id, storage_dir)
    target_path = project_dir / "jobs" / f"{job_id}.json"

    with open(target_path, "w", encoding="utf-8") as f:
        json.dump(job, f, indent=2)


def load_job(
    project_id: str,
    job_id: str,
    storage_dir: Path,
) -> Optional[Dict[str, Any]]:
    """Reads and returns the job record."""
    target_path = (
        storage_dir
        / "seo_projects"
        / project_id
        / "jobs"
        / f"{job_id}.json"
    )

    if target_path.exists():
        with open(target_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def list_jobs(project_id: str, storage_dir: Path) -> List[Dict[str, Any]]:
    """Returns all job records for the project."""
    jobs_dir = storage_dir / "seo_projects" / project_id / "jobs"
    if not jobs_dir.exists():
        return []

    jobs = []
    for f in jobs_dir.glob("*.json"):
        try:
            with open(f, "r", encoding="utf-8") as fp:
                jobs.append(json.load(fp))
        except (json.JSONDecodeError, IOError):
            continue

    return jobs
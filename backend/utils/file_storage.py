import os
import uuid

from config import settings


def build_upload_path(project_code: str, original_filename: str) -> tuple[str, str]:
    """Returns (absolute_disk_path, stored_file_name) for a new upload."""
    project_dir = os.path.join(settings.UPLOAD_DIR, project_code)
    os.makedirs(project_dir, exist_ok=True)

    ext = os.path.splitext(original_filename)[1]
    stored_name = f"{uuid.uuid4().hex}{ext}"
    return os.path.join(project_dir, stored_name), stored_name

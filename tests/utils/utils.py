from pathlib import Path
import random
from labelu.internal.common.config import settings
import string


def random_lower_string() -> str:
    return "".join(random.choices(string.ascii_lowercase, k=16))


def random_username() -> str:
    return f"{random_lower_string()}@{random_lower_string()}.com"

def empty_task_upload(task_id: int, input_filename: str) -> str:
    from labelu.internal.common.storage import get_storage_backend

    key = f"upload/{task_id}/{input_filename}"
    get_storage_backend().delete(key)
    return key

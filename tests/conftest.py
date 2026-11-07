import os
import shutil
import tempfile
from pathlib import Path
from typing import Dict, Generator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

# 1. 数据库与对象存储均使用合成数据，不读取开发者的配置或凭据。
_TEST_DATA_DIR = Path(tempfile.mkdtemp(prefix="labelu-test-"))
os.environ["DATABASE_URL"] = f"sqlite:///{(_TEST_DATA_DIR / 'application.sqlite').as_posix()}"
os.environ["BASE_DATA_DIR"] = str(_TEST_DATA_DIR)
os.environ["PASSWORD_SECRET_KEY"] = "labelu-test-only-signing-key"
os.environ["S3_BUCKET"] = "labelu-test"
os.environ["S3_ENDPOINT"] = ""
os.environ["S3_REGION"] = "us-east-1"
os.environ["S3_ACCESS_KEY_ID"] = "testing"
os.environ["S3_SECRET_ACCESS_KEY"] = "testing"

import boto3
from moto import mock_aws

_s3_mock = mock_aws()
_s3_mock.start()
_s3_client = boto3.client("s3", region_name="us-east-1",
                          aws_access_key_id="testing", aws_secret_access_key="testing")
_s3_client.create_bucket(Bucket="labelu-test")

from labelu.internal.common.config import settings
from labelu.internal.common.storage import get_storage_backend

from labelu.main import app
from labelu.internal.common.db import Base
from labelu.internal.common.db import begin_transaction
from labelu.internal.common.db import get_db
from labelu.internal.common.security import get_password_hash
from labelu.internal.domain.models.user import User
from labelu.internal.adapter.persistence import crud_user

TEST_USERNAME = "test@example.com"
TEST_USER_PASSWORD = "test@123"


SQLALCHEMY_DATABASE_URL = f"sqlite:///{_TEST_DATA_DIR / 'test.db'}"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 30},
)
TestingSessionLocal = sessionmaker(autoflush=False, bind=engine)
Base.metadata.create_all(bind=engine)


@pytest.fixture(autouse=True, scope="session")
def _hermetic_storage() -> Generator:
    """Guarantee the isolated media root is active and clean it up afterwards.

    The redirect itself happens at import time (above); this fixture re-clears
    the storage-backend cache in case anything memoized it during collection and
    removes the throwaway directory (test DB + media) once the session ends.
    """
    get_storage_backend.cache_clear()
    try:
        yield
    finally:
        engine.dispose()
        get_storage_backend.cache_clear()
        _s3_mock.stop()
        shutil.rmtree(_TEST_DATA_DIR, ignore_errors=True)


def override_get_db():
    db = None
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        if db is not None:
            db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(autouse=True, scope="session")
def db() -> Generator:
    db = None
    try:
        db = TestingSessionLocal()
        # Seed the test user at session scope so it exists before the
        # module-scoped ``testuser_token_headers`` fixture logs in. The
        # per-test ``run_around_tests`` cleanup preserves the ``user`` table, so
        # this single seed lasts the whole session. (Previously the user
        # survived only because ``test.db`` persisted in the cwd across runs.)
        init_db()
        yield db
    finally:
        if db is not None:
            db.close()


@pytest.fixture(scope="session", autouse=True)
def ensure_test_user() -> Generator:
    # Initialize test user once per test session
    init_db()
    yield


@pytest.fixture(autouse=True)
def run_around_tests(db: Session):
    init_db()
    yield
    # Release any autobegin transaction on the session-scoped fixture so SQLite
    # teardown and TestClient requests do not deadlock.
    db.rollback()
    cleanup = None
    try:
        cleanup = TestingSessionLocal()
        meta = Base.metadata
        with begin_transaction(cleanup):
            for table in reversed(meta.sorted_tables):
                if table.key != "user":
                    cleanup.execute(table.delete())
        objects = _s3_client.list_objects_v2(Bucket="labelu-test").get("Contents", [])
        for obj in objects:
            _s3_client.delete_object(Bucket="labelu-test", Key=obj["Key"])
    finally:
        if cleanup is not None:
            cleanup.close()


@pytest.fixture(scope="module")
def client() -> Generator:
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def testuser_token_headers(client: TestClient) -> Dict[str, str]:
    return get_testuser_token_headers(client)


def get_testuser_token_headers(client: TestClient) -> Dict[str, str]:
    data = {
        "username": TEST_USERNAME,
        "password": TEST_USER_PASSWORD,
    }
    r = client.post(f"{settings.API_V1_STR}/users/login", json=data)
    response_json = r.json()

    # Add debugging info for CI failures
    if "data" not in response_json:
        print(f"Login failed. Response: {response_json}")
        print(f"Status code: {r.status_code}")
        print(f"Password length (bytes): {len(TEST_USER_PASSWORD.encode('utf-8'))}")
        raise ValueError(f"Login failed with response: {response_json}")

    token = response_json["data"]["token"]
    headers = {"Authorization": f"{token}"}
    return headers


def init_db() -> None:
    db = None
    try:
        db = TestingSessionLocal()
        with begin_transaction(db):
            user = crud_user.get_user_by_username(db, username=TEST_USERNAME)
            if not user:
                user_in = User(
                    username=TEST_USERNAME,
                    hashed_password=get_password_hash(TEST_USER_PASSWORD),
                )
                user = crud_user.create(db=db, user=user_in)
            from labelu.internal.common.crypto import encrypt_value
            from labelu.internal.domain.models.data_source import DataSource

            if db.query(DataSource).filter(DataSource.id == 1).first() is None:
                db.add(DataSource(id=1, name="Test S3 dataset", bucket="labelu-test",
                                  prefix="datasets", region="us-east-1", path_style=True,
                                  access_key_id=encrypt_value("testing"),
                                  secret_access_key=encrypt_value("testing"),
                                  created_by=user.id, updated_by=user.id))
    finally:
        if db is not None:
            db.close()

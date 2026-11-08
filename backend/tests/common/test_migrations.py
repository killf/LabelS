import os
import subprocess
import sys
from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

from backend.common.db import Base


def test_initial_schema_round_trip_preserves_data_on_repeated_upgrade(tmp_path: Path):
    """用隔离 SQLite 验证完整结构、重复升级保留数据及完整回退。"""
    config = Config()
    directory = Path(__file__).resolve().parents[2] / "migrations"
    config.set_main_option("script_location", str(directory))
    database_url = f"sqlite:///{(tmp_path / 'initial.sqlite').as_posix()}"
    config.set_main_option("sqlalchemy.url", database_url)
    engine = create_engine(database_url)

    try:
        # 1. 直接从空库建立所有表、索引与外键，不预先调用 ORM 建表。
        command.upgrade(config, "head")
        with engine.begin() as connection:
            context = MigrationContext.configure(connection)
            assert compare_metadata(context, Base.metadata) == []
            connection.execute(text("INSERT INTO task (id) VALUES (1)"))
            connection.execute(
                text("INSERT INTO auto_label_job (id, task_id) VALUES (1, 1)")
            )
            connection.execute(
                text("INSERT INTO task_sample (id, task_id) VALUES (1, 1)")
            )
            assert (
                connection.execute(text("SELECT ai_algorithm FROM task")).scalar_one()
                == "yolo"
            )
            assert (
                connection.execute(
                    text("SELECT model_name FROM auto_label_job")
                ).scalar_one()
                == ""
            )
            assert (
                connection.execute(text("SELECT split FROM task_sample")).scalar_one()
                == "train"
            )
            connection.execute(
                text(
                    "INSERT INTO user (id, username) VALUES (1, 'initial@example.com')"
                )
            )

        # 2. 再次运行初始化入口时，已有业务数据保持不变。
        command.upgrade(config, "head")
        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT username FROM user")
            ).scalar_one() == ("initial@example.com")

        # 3. 回退删除全部业务结构，并允许重新初始化。
        command.downgrade(config, "base")
        assert set(inspect(engine).get_table_names()) == {"alembic_version"}
        command.upgrade(config, "head")
        with engine.connect() as connection:
            context = MigrationContext.configure(connection)
            assert compare_metadata(context, Base.metadata) == []
    finally:
        engine.dispose()


def _run_isolated_app(tmp_path: Path, script: str) -> None:
    """用独立进程与合成配置检查启动，避免复用测试进程的数据库全局状态。"""
    database = tmp_path / "data" / "application.sqlite"
    env = {
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        "PYTHONPATH": str(Path(__file__).resolve().parents[3]),
        "TEMP": str(tmp_path),
        "TMP": str(tmp_path),
        "DATABASE_URL": f"sqlite:///{database.as_posix()}",
        "PASSWORD_SECRET_KEY": "startup-test-only-key",
    }
    result = subprocess.run(
        [sys.executable, "-c", script, str(database)],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_import_and_cli_help_do_not_create_database(tmp_path: Path):
    _run_isolated_app(
        tmp_path,
        """
import sys
from pathlib import Path
from click.testing import CliRunner
from backend.main import cli

database = Path(sys.argv[1])
result = CliRunner().invoke(cli, ['--help'])
assert result.exit_code == 0, result.output
assert 'migrate_to_mysql' not in result.output
assert not database.parent.exists()
""",
    )


def test_startup_initializes_database_and_marks_interrupted_jobs(tmp_path: Path):
    _run_isolated_app(
        tmp_path,
        """
import sqlite3
import sys
from pathlib import Path
from fastapi.testclient import TestClient
from backend.main import app

database = Path(sys.argv[1])
assert not database.exists()
with TestClient(app) as client:
    assert client.get('/openapi.json').json()['info']['version'] == '2.0.0'
    with sqlite3.connect(database) as connection:
        connection.execute("INSERT INTO auto_label_job (id, status, model_name) VALUES (1, 'PENDING', 'fake.pt')")
with TestClient(app):
    with sqlite3.connect(database) as connection:
        assert connection.execute('SELECT status FROM auto_label_job WHERE id = 1').fetchone() == ('FAILED',)
""",
    )


def test_memory_database_url_needs_no_data_directory(tmp_path: Path):
    _run_isolated_app(
        tmp_path,
        """
import os
import sys
from pathlib import Path
os.environ['DATABASE_URL'] = 'sqlite://'
from backend.migrations.run_migrate import run_db_migrations
run_db_migrations()
assert not Path(sys.argv[1]).parent.exists()
""",
    )

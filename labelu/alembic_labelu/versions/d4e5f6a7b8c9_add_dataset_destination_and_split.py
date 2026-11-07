"""为任务增加 S3 数据集目标，为样本增加训练、测试、评估划分。"""

from alembic import op
import sqlalchemy as sa

revision = "d4e5f6a7b8c9"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 新库由 ORM 建表，已有 SQLite 数据库只补充缺少的列。
    inspector = sa.inspect(op.get_bind())
    task_columns = {column["name"] for column in inspector.get_columns("task")}
    with op.batch_alter_table("task") as batch:
        if "dataset_data_source_id" not in task_columns:
            batch.add_column(
                sa.Column("dataset_data_source_id", sa.Integer(), nullable=True)
            )
            batch.create_foreign_key(
                "fk_task_dataset_source",
                "data_source",
                ["dataset_data_source_id"],
                ["id"],
            )
        if "dataset_prefix" not in task_columns:
            batch.add_column(
                sa.Column(
                    "dataset_prefix", sa.String(1024), nullable=False, server_default=""
                )
            )

    sample_columns = {column["name"] for column in inspector.get_columns("task_sample")}
    if "split" not in sample_columns:
        op.add_column(
            "task_sample",
            sa.Column("split", sa.String(16), nullable=False, server_default="train"),
        )


def downgrade() -> None:
    with op.batch_alter_table("task_sample") as batch:
        batch.drop_column("split")

    with op.batch_alter_table("task") as batch:
        batch.drop_column("dataset_data_source_id")
        batch.drop_column("dataset_prefix")

"""记录任务选用的 YOLO 权重及每次批量预标注使用的模型。"""

from alembic import op
import sqlalchemy as sa

revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "ai_model_name" not in {column["name"] for column in inspector.get_columns("task")}:
        op.add_column("task", sa.Column("ai_model_name", sa.String(1024), nullable=True))

    if "model_name" not in {column["name"] for column in inspector.get_columns("auto_label_job")}:
        op.add_column("auto_label_job", sa.Column("model_name", sa.String(1024),
                                                 nullable=False, server_default=""))


def downgrade() -> None:
    with op.batch_alter_table("auto_label_job") as batch:
        batch.drop_column("model_name")

    with op.batch_alter_table("task") as batch:
        batch.drop_column("ai_model_name")

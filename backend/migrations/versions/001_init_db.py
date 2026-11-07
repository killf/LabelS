"""创建 LabelS 2.0.0 的完整初始表结构、索引和外键。"""

from alembic import op
import sqlalchemy as sa

# 保留当前修订 ID；已处于该版本的数据库无需重新建表。
revision = "e5f6a7b8c9d0"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """在空数据库中建立完整业务结构，不读取应用模型或历史数据。"""
    # 1. 创建账户表及其索引。
    op.create_table(
        "user",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("username", sa.String(length=50), nullable=True),
        sa.Column("hashed_password", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Time a task was created",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Last time a task was updated",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_user_id"), "user", ["id"], unique=False)
    op.create_index(op.f("ix_user_username"), "user", ["username"], unique=True)

    # 2. 创建S3 数据源表及其索引。
    op.create_table(
        "data_source",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "name", sa.String(length=128), nullable=False, comment="Display name"
        ),
        sa.Column(
            "type", sa.String(length=32), nullable=False, comment="Source type: S3"
        ),
        sa.Column(
            "endpoint", sa.String(length=512), nullable=True, comment="S3 endpoint URL"
        ),
        sa.Column("region", sa.String(length=64), nullable=True, comment="AWS region"),
        sa.Column(
            "bucket", sa.String(length=256), nullable=False, comment="Bucket name"
        ),
        sa.Column(
            "prefix", sa.String(length=512), nullable=True, comment="Default key prefix"
        ),
        sa.Column(
            "access_key_id",
            sa.String(length=512),
            nullable=True,
            comment="Encrypted access key",
        ),
        sa.Column(
            "secret_access_key",
            sa.String(length=1024),
            nullable=True,
            comment="Encrypted secret key",
        ),
        sa.Column(
            "path_style",
            sa.Boolean(),
            nullable=True,
            comment="Use path-style addressing",
        ),
        sa.Column("use_ssl", sa.Boolean(), nullable=True, comment="Use HTTPS"),
        sa.Column(
            "presign_expire_secs",
            sa.Integer(),
            nullable=True,
            comment="Presigned URL TTL",
        ),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Created time",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Updated time",
        ),
        sa.Column(
            "deleted_at", sa.DateTime(), nullable=True, comment="Soft delete time"
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["user.id"],
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["user.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_datasource_id_deleted_at",
        "data_source",
        ["id", "deleted_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_data_source_created_by"), "data_source", ["created_by"], unique=False
    )
    op.create_index(
        op.f("ix_data_source_deleted_at"), "data_source", ["deleted_at"], unique=False
    )
    op.create_index(op.f("ix_data_source_id"), "data_source", ["id"], unique=False)
    op.create_index(
        op.f("ix_data_source_updated_by"), "data_source", ["updated_by"], unique=False
    )

    # 3. 创建任务与数据集配置表及其索引。
    op.create_table(
        "task",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=64), nullable=True),
        sa.Column(
            "description",
            sa.String(length=1024),
            nullable=True,
            comment="task description",
        ),
        sa.Column("tips", sa.String(length=1024), nullable=True, comment="task tips"),
        sa.Column(
            "dataset_data_source_id",
            sa.Integer(),
            nullable=True,
            comment="YOLO 数据集的目标 S3 数据源",
        ),
        sa.Column(
            "dataset_prefix",
            sa.String(length=1024),
            server_default="",
            nullable=False,
            comment="相对于数据源前缀的数据集目录",
        ),
        sa.Column(
            "ai_model_name",
            sa.String(length=1024),
            nullable=True,
            comment="models/ 下用于 AI 标注的权重文件名",
        ),
        sa.Column(
            "last_sample_inner_id",
            sa.Integer(),
            nullable=True,
            comment="The last inner id of sample in a task",
        ),
        sa.Column("config", sa.Text(), nullable=True, comment="task config yaml"),
        sa.Column(
            "media_type",
            sa.String(length=32),
            nullable=True,
            comment="task media type: image, video, audio",
        ),
        sa.Column("status", sa.String(length=32), nullable=True, comment="task status"),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column(
            "updated_by",
            sa.Integer(),
            nullable=True,
            comment="Last time a task was updated by",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Time a task was created",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Last time a task was updated",
        ),
        sa.Column(
            "deleted_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Task delete time",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["user.id"],
        ),
        sa.ForeignKeyConstraint(
            ["dataset_data_source_id"],
            ["data_source.id"],
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["user.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_task_id_deleted_at_index", "task", ["id", "deleted_at"], unique=False
    )
    op.create_index(op.f("ix_task_created_by"), "task", ["created_by"], unique=False)
    op.create_index(op.f("ix_task_deleted_at"), "task", ["deleted_at"], unique=False)
    op.create_index(op.f("ix_task_id"), "task", ["id"], unique=False)
    op.create_index(op.f("ix_task_name"), "task", ["name"], unique=False)

    # 4. 创建AI 预标注批次表及其索引。
    op.create_table(
        "auto_label_job",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=True),
        sa.Column("sample_count", sa.Integer(), nullable=True),
        sa.Column("processed_count", sa.Integer(), nullable=True),
        sa.Column("success_count", sa.Integer(), nullable=True),
        sa.Column("failed_count", sa.Integer(), nullable=True),
        sa.Column(
            "model_name",
            sa.String(length=1024),
            server_default="",
            nullable=False,
            comment="本批次使用的权重文件名",
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["user.id"],
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["task.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_auto_label_job_id"), "auto_label_job", ["id"], unique=False
    )
    op.create_index(
        op.f("ix_auto_label_job_task_id"), "auto_label_job", ["task_id"], unique=False
    )

    # 5. 创建图片与附件引用表及其索引。
    op.create_table(
        "task_attachment",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "filename", sa.String(length=256), nullable=True, comment="file name"
        ),
        sa.Column("url", sa.String(length=256), nullable=True, comment="file url"),
        sa.Column(
            "path",
            sa.String(length=256),
            nullable=True,
            comment="file storage path or S3 object key",
        ),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column(
            "data_source_id",
            sa.Integer(),
            nullable=True,
            comment="NULL = global S3 upload, set = external S3 data source",
        ),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Time a task was created",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Last time a task was updated",
        ),
        sa.Column(
            "deleted_at", sa.DateTime(), nullable=True, comment="Task delete time"
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["user.id"],
        ),
        sa.ForeignKeyConstraint(
            ["data_source_id"],
            ["data_source.id"],
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["task.id"],
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["user.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_attachment_id_deleted_at",
        "task_attachment",
        ["id", "deleted_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_task_attachment_created_by"),
        "task_attachment",
        ["created_by"],
        unique=False,
    )
    op.create_index(
        op.f("ix_task_attachment_data_source_id"),
        "task_attachment",
        ["data_source_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_task_attachment_deleted_at"),
        "task_attachment",
        ["deleted_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_task_attachment_id"), "task_attachment", ["id"], unique=False
    )
    op.create_index(
        op.f("ix_task_attachment_task_id"), "task_attachment", ["task_id"], unique=False
    )
    op.create_index(
        op.f("ix_task_attachment_updated_by"),
        "task_attachment",
        ["updated_by"],
        unique=False,
    )

    # 6. 创建任务协作者表及其索引。
    op.create_table(
        "task_collaborator",
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Time a task collaborator was created",
        ),
        sa.ForeignKeyConstraint(["task_id"], ["task.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("task_id", "user_id"),
    )
    op.create_index(
        op.f("ix_task_collaborator_task_id"),
        "task_collaborator",
        ["task_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_task_collaborator_user_id"),
        "task_collaborator",
        ["user_id"],
        unique=False,
    )

    # 7. 创建样本预标注表及其索引。
    op.create_table(
        "task_pre_annotation",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=True, comment="Task ID"),
        sa.Column(
            "sample_name",
            sa.String(length=255),
            nullable=True,
            comment="One of the sample names of the task",
        ),
        sa.Column("file_id", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Time a task sample result was created",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Last time a task pre annotation result was updated",
        ),
        sa.Column(
            "data",
            sa.Text(),
            nullable=True,
            comment="task sample pre annotation result",
        ),
        sa.Column(
            "deleted_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Task pre-annotation delete time",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["user.id"],
        ),
        sa.ForeignKeyConstraint(
            ["file_id"],
            ["task_attachment.id"],
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["task.id"],
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["user.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_pre_annotation_id_deleted_at",
        "task_pre_annotation",
        ["id", "deleted_at"],
        unique=False,
    )
    op.create_index(
        "idx_pre_annotation_sample_name",
        "task_pre_annotation",
        ["sample_name"],
        unique=False,
    )
    op.create_index(
        op.f("ix_task_pre_annotation_created_by"),
        "task_pre_annotation",
        ["created_by"],
        unique=False,
    )
    op.create_index(
        op.f("ix_task_pre_annotation_deleted_at"),
        "task_pre_annotation",
        ["deleted_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_task_pre_annotation_file_id"),
        "task_pre_annotation",
        ["file_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_task_pre_annotation_id"), "task_pre_annotation", ["id"], unique=False
    )
    op.create_index(
        op.f("ix_task_pre_annotation_sample_name"),
        "task_pre_annotation",
        ["sample_name"],
        unique=False,
    )
    op.create_index(
        op.f("ix_task_pre_annotation_task_id"),
        "task_pre_annotation",
        ["task_id"],
        unique=False,
    )

    # 8. 创建样本与数据集划分表及其索引。
    op.create_table(
        "task_sample",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "inner_id", sa.Integer(), nullable=True, comment="sample id in a task"
        ),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("file_id", sa.Integer(), nullable=True),
        sa.Column(
            "split",
            sa.String(length=16),
            server_default="train",
            nullable=False,
            comment="训练、测试或评估集",
        ),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Time a task sample result was created",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Last time a task sample result was updated",
        ),
        sa.Column(
            "annotated_count",
            sa.Integer(),
            nullable=True,
            comment="task sample result count",
        ),
        sa.Column("data", sa.Text(), nullable=True, comment="task sample result"),
        sa.Column(
            "state",
            sa.String(length=32),
            nullable=True,
            comment="NEW is has not start yet, DONE is completed, SKIPPED is skipped",
        ),
        sa.Column(
            "deleted_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Task delete time",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["user.id"],
        ),
        sa.ForeignKeyConstraint(
            ["file_id"],
            ["task_attachment.id"],
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["task.id"],
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["user.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_sample_id_deleted_at", "task_sample", ["id", "deleted_at"], unique=False
    )
    op.create_index(
        op.f("ix_task_sample_created_by"), "task_sample", ["created_by"], unique=False
    )
    op.create_index(
        op.f("ix_task_sample_deleted_at"), "task_sample", ["deleted_at"], unique=False
    )
    op.create_index(
        op.f("ix_task_sample_file_id"), "task_sample", ["file_id"], unique=False
    )
    op.create_index(op.f("ix_task_sample_id"), "task_sample", ["id"], unique=False)
    op.create_index(
        op.f("ix_task_sample_task_id"), "task_sample", ["task_id"], unique=False
    )

    # 9. 创建样本更新者表及其索引。
    op.create_table(
        "task_sample_updater",
        sa.Column("sample_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="created time",
        ),
        sa.ForeignKeyConstraint(["sample_id"], ["task_sample.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("sample_id", "user_id"),
    )
    op.create_index(
        op.f("ix_task_sample_updater_sample_id"),
        "task_sample_updater",
        ["sample_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_task_sample_updater_user_id"),
        "task_sample_updater",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    """按外键依赖的逆序删除初始化脚本创建的索引和业务表。"""

    op.drop_index(
        op.f("ix_task_sample_updater_user_id"), table_name="task_sample_updater"
    )
    op.drop_index(
        op.f("ix_task_sample_updater_sample_id"), table_name="task_sample_updater"
    )

    op.drop_table("task_sample_updater")
    op.drop_index(op.f("ix_task_sample_task_id"), table_name="task_sample")
    op.drop_index(op.f("ix_task_sample_id"), table_name="task_sample")
    op.drop_index(op.f("ix_task_sample_file_id"), table_name="task_sample")
    op.drop_index(op.f("ix_task_sample_deleted_at"), table_name="task_sample")
    op.drop_index(op.f("ix_task_sample_created_by"), table_name="task_sample")
    op.drop_index("idx_sample_id_deleted_at", table_name="task_sample")

    op.drop_table("task_sample")
    op.drop_index(
        op.f("ix_task_pre_annotation_task_id"), table_name="task_pre_annotation"
    )
    op.drop_index(
        op.f("ix_task_pre_annotation_sample_name"), table_name="task_pre_annotation"
    )
    op.drop_index(op.f("ix_task_pre_annotation_id"), table_name="task_pre_annotation")
    op.drop_index(
        op.f("ix_task_pre_annotation_file_id"), table_name="task_pre_annotation"
    )
    op.drop_index(
        op.f("ix_task_pre_annotation_deleted_at"), table_name="task_pre_annotation"
    )
    op.drop_index(
        op.f("ix_task_pre_annotation_created_by"), table_name="task_pre_annotation"
    )
    op.drop_index("idx_pre_annotation_sample_name", table_name="task_pre_annotation")
    op.drop_index("idx_pre_annotation_id_deleted_at", table_name="task_pre_annotation")

    op.drop_table("task_pre_annotation")
    op.drop_index(op.f("ix_task_collaborator_user_id"), table_name="task_collaborator")
    op.drop_index(op.f("ix_task_collaborator_task_id"), table_name="task_collaborator")

    op.drop_table("task_collaborator")
    op.drop_index(op.f("ix_task_attachment_updated_by"), table_name="task_attachment")
    op.drop_index(op.f("ix_task_attachment_task_id"), table_name="task_attachment")
    op.drop_index(op.f("ix_task_attachment_id"), table_name="task_attachment")
    op.drop_index(op.f("ix_task_attachment_deleted_at"), table_name="task_attachment")
    op.drop_index(
        op.f("ix_task_attachment_data_source_id"), table_name="task_attachment"
    )
    op.drop_index(op.f("ix_task_attachment_created_by"), table_name="task_attachment")
    op.drop_index("idx_attachment_id_deleted_at", table_name="task_attachment")

    op.drop_table("task_attachment")
    op.drop_index(op.f("ix_auto_label_job_task_id"), table_name="auto_label_job")
    op.drop_index(op.f("ix_auto_label_job_id"), table_name="auto_label_job")

    op.drop_table("auto_label_job")
    op.drop_index(op.f("ix_task_name"), table_name="task")
    op.drop_index(op.f("ix_task_id"), table_name="task")
    op.drop_index(op.f("ix_task_deleted_at"), table_name="task")
    op.drop_index(op.f("ix_task_created_by"), table_name="task")
    op.drop_index("idx_task_id_deleted_at_index", table_name="task")

    op.drop_table("task")
    op.drop_index(op.f("ix_data_source_updated_by"), table_name="data_source")
    op.drop_index(op.f("ix_data_source_id"), table_name="data_source")
    op.drop_index(op.f("ix_data_source_deleted_at"), table_name="data_source")
    op.drop_index(op.f("ix_data_source_created_by"), table_name="data_source")
    op.drop_index("idx_datasource_id_deleted_at", table_name="data_source")

    op.drop_table("data_source")
    op.drop_index(op.f("ix_user_username"), table_name="user")
    op.drop_index(op.f("ix_user_id"), table_name="user")

    op.drop_table("user")

from fastapi import status

from backend.common.error_code import ErrorCode, LabelSException


def assert_project_access(project, current_user) -> None:
    """Ensure current_user may access the given project's data.

    Access is granted to the project owner or any of its collaborators. Any other
    authenticated user is rejected with 403, closing IDOR/BOLA on project-scoped
    resources (samples, pre-annotations, exports, ...).
    """
    collaborator_ids = {c.id for c in project.collaborators}
    if (
        project.created_by != current_user.id
        and current_user.id not in collaborator_ids
    ):
        raise LabelSException(
            code=ErrorCode.CODE_30001_NO_PERMISSION,
            status_code=status.HTTP_403_FORBIDDEN,
        )


def assert_owner(resource, current_user) -> None:
    """Ensure current_user owns the resource (created_by).

    Used for user-private resources without a collaborator concept
    (e.g. data sources).
    """
    if resource.created_by != current_user.id:
        raise LabelSException(
            code=ErrorCode.CODE_30001_NO_PERMISSION,
            status_code=status.HTTP_403_FORBIDDEN,
        )

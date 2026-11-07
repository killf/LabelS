from datetime import timedelta
from typing import List, Tuple

from loguru import logger
from fastapi import status
from sqlalchemy.orm import Session

from backend.domain.models.user import User
from backend.adapter.persistence import crud_user
from backend.common.db import begin_transaction
from backend.common.config import settings
from backend.common.error_code import ErrorCode
from backend.common.error_code import LabelSException
from backend.common.security import AccessToken
from backend.common.security import verify_password
from backend.common.security import get_password_hash
from backend.common.security import create_access_token
from backend.application.command.user import LoginCommand
from backend.application.command.user import SignupCommand
from backend.application.response.user import UserResponse
from backend.application.response.user import LoginResponse


async def signup(db: Session, cmd: SignupCommand) -> UserResponse:
    # check user alredy exists
    user = crud_user.get_user_by_username(db, username=cmd.username)
    if user:
        logger.error("user already exist:{}", cmd.username)
        raise LabelSException(
            code=ErrorCode.CODE_40001_USERNAME_ALREADY_EXISTS,
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    # new a user
    with begin_transaction(db):
        user = crud_user.create(
            db,
            User(
                username=cmd.username,
                hashed_password=get_password_hash(cmd.password),
            ),
        )

    # response
    return UserResponse(id=user.id, username=user.username)


async def list_by(
    db: Session, page: int, size: int, username: str = None
) -> Tuple[List[UserResponse], int]:
    # get all users
    users, total = crud_user.list_by(db, page, size, username)

    # response
    return [UserResponse(id=user.id, username=user.username) for user in users], total


async def login(db: Session, cmd: LoginCommand) -> LoginResponse:

    # check user exsit and verify password
    user = crud_user.get_user_by_username(db, cmd.username)
    if not user or not verify_password(cmd.password, user.hashed_password):
        raise LabelSException(
            code=ErrorCode.CODE_40000_USERNAME_OR_PASSWORD_INCORRECT,
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    # create access token
    access_token_expires = timedelta(minutes=settings.TOKEN_ACCESS_EXPIRE_MINUTES)
    access_token = create_access_token(
        token=AccessToken(id=user.id, username=user.username),
        expires_delta=access_token_expires,
    )

    # response
    return LoginResponse(token=f"{settings.TOKEN_TYPE} {access_token}")

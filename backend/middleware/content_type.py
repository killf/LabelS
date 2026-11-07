from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from backend.version import version as labels_version


class ContentTypeMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        # add LabelS-Version header
        response.headers["LabelS-Version"] = labels_version

        # set content-type for javascript files
        if request.url.path.endswith(".js"):
            response.headers["content-type"] = "application/javascript"

        return response

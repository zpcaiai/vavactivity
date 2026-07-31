from typing import Any

from pydantic import BaseModel


class ResponseMeta(BaseModel):
    request_id: str


class SuccessResponse[T](BaseModel):
    data: T
    meta: ResponseMeta


def success[T](data: T, request_id: str) -> dict[str, Any]:
    return {"data": data, "meta": {"request_id": request_id}}

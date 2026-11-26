from typing import Annotated

from fastapi import Path
from pydantic import JsonValue

from src.core.dto.base import BaseDTO

PositiveID = Annotated[int, Path(gt=0, le=2**31 - 1)]


class ErrorResponse(BaseDTO):
    detail: str | list[dict[str, JsonValue]]

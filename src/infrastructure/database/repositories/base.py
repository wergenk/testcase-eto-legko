from functools import lru_cache

from pydantic import TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession


class BaseRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @staticmethod
    @lru_cache(maxsize=64)
    def _get_adapter[T](_type: type[T]) -> TypeAdapter[T]:
        return TypeAdapter(_type)

    @classmethod
    def _validate[T](cls, _type: type[T], values: object) -> T | None:
        if values is None:
            return None
        return cls._get_adapter(_type).validate_python(values)

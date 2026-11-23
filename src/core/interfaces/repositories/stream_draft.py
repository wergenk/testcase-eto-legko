from abc import ABC, abstractmethod

from src.core.dto import CreateStreamDraftDTO, StreamDraft


class StreamDraftRepository(ABC):
    """Один рабочий черновик на поток, включая активные и архивные офферы.

    Черновик и его строки сохраняются атомарно. Методы не коммитят
    транзакцию самостоятельно. Базовый снимок должен принадлежать потоку.
    Внутри черновика keitaro_offer_id уникален.
    """

    @abstractmethod
    async def create(self, data: CreateStreamDraftDTO) -> StreamDraft:
        """Создать черновик вместе с офферами с начальной revision=1."""
        raise NotImplementedError

    @abstractmethod
    async def get(self, draft_id: int) -> StreamDraft | None:
        """Загрузить черновик целиком; офферы упорядочены по position и offer id."""
        raise NotImplementedError

    @abstractmethod
    async def get_by_stream(self, stream_id: int) -> StreamDraft | None:
        """Загрузить рабочий черновик потока вместе со всеми его офферами."""
        raise NotImplementedError

    @abstractmethod
    async def update(
        self,
        draft: StreamDraft,
        *,
        expected_revision: int,
    ) -> StreamDraft | None:
        """Атомарно сохранить состав, базовое состояние и ссылку на снимок.

        Проверить сохранённую revision, а не значение из DTO. При совпадении
        записать expected_revision + 1 и вернуть обновлённый черновик.
        При конфликте версии, идентичности потока или отсутствии черновика
        вернуть None, ничего не изменяя. Строки, отсутствующие в draft.offers,
        удаляются;
        архивные строки должны явно присутствовать в переданном составе.
        stream_id существующего черновика изменять нельзя.
        """
        raise NotImplementedError

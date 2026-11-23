class KeitaroError(Exception):
    """Ошибка обращения к Keitaro или обработки его ответа."""


class KeitaroNotFoundError(KeitaroError):
    """Запрошенный объект не найден в Keitaro."""


class OfferShareError(ValueError):
    """Невозможно распределить доли офферов с заданными ограничениями."""


class StreamDraftError(Exception):
    """Ошибка редактирования черновика потока."""


class StreamDraftNotFoundError(StreamDraftError):
    """Черновик не найден."""


class StreamDraftConflictError(StreamDraftError):
    """Черновик изменился после загрузки клиентом."""


class DraftOfferError(StreamDraftError):
    """Операция с оффером черновика недопустима."""

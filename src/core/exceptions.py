class KeitaroError(Exception):
    """Ошибка обращения к Keitaro или обработки его ответа."""


class KeitaroNotFoundError(KeitaroError):
    """Запрошенный объект не найден в Keitaro."""


class KeitaroAuthorizationError(KeitaroError):
    """Keitaro отклонил API-ключ или доступ к ресурсу."""


class KeitaroTimeoutError(KeitaroError):
    """Истекло время ожидания ответа Keitaro."""


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


class StreamPublicationConflictError(StreamDraftConflictError):
    """Состав офферов или схема потока в Keitaro изменились после Fetch."""


class StreamPublicationError(StreamDraftError):
    """Результат публикации не совпадает с ожидаемым состоянием."""


class CampaignCreationError(Exception):
    """Не удалось завершить создание кампании."""


class CampaignCreationConflictError(CampaignCreationError):
    """Ключ запроса или удалённые объекты содержат другие настройки."""

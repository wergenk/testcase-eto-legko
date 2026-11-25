# Adrobot


Реализованы DTO, ABC-контракты репозиториев и Keitaro, пересчёт долей,
SQLAlchemy-модели, первая миграция, SQL-репозитории, UnitOfWork и сервис
локального редактора черновиков, HTTP-адаптер Keitaro и синхронизация Fetch/Push.
HTTP API приложения и создаватель кампаний пока не реализованы.

## Зависимости

```powershell
uv sync
```

## Подключение к Keitaro

В локальном `.env` задайте:

```dotenv
KEITARO__BASE_URL=https://keitaro-for-tests.etolegko.com/admin_api/v1/
KEITARO__API_KEY=your-api-key
KEITARO__TIMEOUT_SECONDS=15
```

Адрес включает `/admin_api/v1`; завершающий слеш необязателен.
Ключ хранится как `SecretStr`. В `.env.example` только заглушка.
Отсутствие всей секции Keitaro допустимо для миграций и локальных операций.

`HttpKeitaroGateway` реализует пять методов `KeitaroGateway`:
`get_campaign_streams`, `get_stream`, `list_offers`, `get_offer`,
`replace_stream_offers`. Использование внутри асинхронного кода:

```python
from src.config import get_settings
from src.infrastructure.keitaro import HttpKeitaroGateway

settings = get_settings()
if settings.keitaro is None:
    raise RuntimeError("Настройте подключение к Keitaro в .env")

async with HttpKeitaroGateway(settings.keitaro) as gateway:
    offers = await gateway.list_offers()
```

Для долгоживущего экземпляра вызывайте `await gateway.aclose()` при завершении.
Адаптер сохраняет полный JSON потока в `raw_payload`, включая фильтры,
лендинги и действия, даже если редактор их не разбирает.
Лишние поля API не попадают в прикладные DTO.

Публикация отправляет только полный список `offers`, включая пустой список
для очистки привязок. Закрепления долей и локальный архив не передаются.
Адаптер не пересчитывает доли и не повторяет PUT автоматически.

Ошибки: `KeitaroNotFoundError` для 404, `KeitaroAuthorizationError` для 401/403,
`KeitaroTimeoutError` для таймаута, `KeitaroError` для остальных сетевых ошибок,
HTTP-статусов и некорректных ответов. Перенаправления не выполняются.
Сообщения исключений не включают ключ, тело ответа или заголовки запроса.

## Ручная тестовая кампания

По ТЗ создаватель кампаний должен принимать название, GEO и ID оффера,
настраивать домен/группу/источник и создавать два потока. До реализации
создавателя подготовьте аналогичную кампанию в админке:

1. Кампании → Создать. Название `[TEST] Adrobot`, alias `adrobot-test`.
2. Выберите доступные домен, группу и источник. Ротация потоков — по позиции.
3. Добавьте обычный поток `GEO → Google`: фильтр страны Australia (`AU`),
   схема прямого редиректа на `https://www.google.com/`. Офферы не добавляйте.
4. Добавьте поток по умолчанию `Offers`, без фильтров. В схеме
   лендингов/офферов оставьте лендинги пустыми и выберите один оффер с долей 100%.
5. Для проверки редактора как в видео добавьте в этот поток ещё два оффера
   и задайте доли 34%, 33%, 33%. Четвёртый оффер оставьте вне потока для Add.
6. Сохраните кампанию и запомните её ID в Keitaro. Это не локальный ID из БД.

Проверки редактора после реализации Fetch/Push: Add даёт четыре доли по 25%;
Cancel возвращает базовый состав; Remove архивирует оффер; Bring back
восстанавливает его. Закрепите 25% у одного оффера и проверьте распределение
оставшихся 75%. После внешнего удаления оффера повторный Fetch должен
архивировать связь локально, не теряя возможность восстановления.

Документация: [кампании](https://docs.keitaro.io/en/campaigns-and-streams/creating-campaign.html),
[потоки](https://docs.keitaro.io/en/campaigns-and-streams/streams.html).

## База данных и миграции

Используется PostgreSQL. `DB__URL` задаётся в окружении или `.env`.
В `.env.example` указан хост `postgres` для Docker Compose; для локального
запуска Alembic задайте адрес своей PostgreSQL:

```powershell
$env:DB__URL = 'postgresql+asyncpg://adrobot:change-me@127.0.0.1:5432/adrobot'
uv run alembic upgrade head
uv run alembic current
```

Для PostgreSQL из Compose:

```powershell
Copy-Item .env.example .env
docker compose up -d postgres
docker compose run --rm --build --no-deps api uv run --no-sync alembic upgrade head
```

Четыре таблицы: `streams`, `stream_snapshots`, `stream_drafts`, `draft_offers`.
Базовый снимок обязан принадлежать тому же потоку, что и черновик.
Снимки защищены от UPDATE триггером PostgreSQL.

## Редактор черновика

`StreamDraftService` получает репозиторий черновиков и `KeitaroGateway`
через конструктор. Пересчёт выполняет чистая функция `recalculate_offer_shares`.
Методы:

- `add_offer`, `remove_offer`, `restore_offer`;
- `pin_share`, `unpin_share`;
- `cancel_changes`.

Каждый вызов требует `expected_revision`, загруженную клиентом.
Репозиторий атомарно проверяет версию при сохранении. Транзакцией управляет
вызывающий код; сервис не делает commit и не публикует изменения в Keitaro.
`get_offer` вызывается при добавлении и восстановлении для проверки доступности.

Remove архивирует строку, обнуляет долю и снимает закрепление.
Restore возвращает её в распределение без закрепления.
Cancel восстанавливает точные доли, закрепления и архив из `base_editor_state`,
удаляя новые неопубликованные строки. Повторные операции без изменений
не увеличивают revision.

## Загрузка кампании (Fetch)

`CampaignSyncService.fetch_campaign(keitaro_campaign_id)` загружает потоки
и справочник офферов из Keitaro, затем сохраняет локальные изменения одной
транзакцией. Принимает внешний ID кампании, например `367`:

```python
from functools import partial

from src.core.services import CampaignSyncService
from src.infrastructure.database.uow import StreamUnitOfWorkSQLAlchemy

service = CampaignSyncService(
    uow_factory=partial(StreamUnitOfWorkSQLAlchemy, manager),
    keitaro=gateway,
)
result = await service.fetch_campaign(367)
# result.streams: для каждого потока локальный Stream и StreamDraft.
```

Сервис сам открывает UOW и делает commit после успешной обработки всей кампании.
Его не нужно оборачивать в дополнительный UOW. Сетевые запросы выполняются
под общей с Push блокировкой кампании, чтобы Fetch не сохранил ответ,
полученный до параллельной публикации. В Keitaro Fetch ничего не записывает.

- Первый Fetch создаёт потоки, неизменяемые снимки и чистые черновики.
- Потоки без офферов (GEO) тоже сохраняются; фильтры и редиректы остаются
  в полном JSON снимка и не интерпретируются редактором.
- Повторный Fetch обновляет названия, принимает состав, порядок и доли
  из Keitaro без пересчёта, создаёт новые снимки и повышает revision черновиков.
- Исчезнувшие или отключённые привязки получают `is_active=False`, `share=0`,
  `is_pinned=False`. Прежний архив сохраняется, вернувшиеся привязки активируются.
- Закрепления сохраняются у по-прежнему активных строк; их доли берутся из API.
- `base_editor_state` становится точной копией нового локального состояния.
  Поэтому последующий Cancel сохраняет и внешний архив, и новые исходные доли.
- `StreamDraft.is_dirty` сравнивает строки с базовым состоянием, включая
  закрепления и архив. Если изменён хотя бы один локальный черновик кампании,
  весь Fetch завершается `StreamDraftConflictError`; сначала нужен Cancel/Push.
- Два Fetch одной кампании сериализуются транзакционной блокировкой PostgreSQL,
  включая первый импорт. Конкурентная правка редактором защищена revision.

Если любой запрос или сохранение завершается ошибкой, частичного импорта нет.
Потоки, полностью исчезнувшие из API, не удаляются из локальной истории и
не входят в результат текущего Fetch. Удаление целых потоков редактор не реализует.
Проверка грязных черновиков распространяется и на такие исторические потоки.

## Публикация потока (Push)

```python
saved = await service.push_stream(draft_id, expected_revision=revision)
```

Метод `CampaignSyncService` принимает локальный ID черновика и версию клиента.
Он сам открывает UOW, блокирует синхронизации кампании и запись черновика,
проверяет revision. Чистый черновик возвращается без запросов к Keitaro и
без повышения версии. Неизменённый состав с новыми локальными закреплениями
сохраняется без PUT.

Для изменённого черновика Push читает актуальный поток и сравнивает привязки
с базовым снимком: ID оффера, целая доля, состояние. Порядок массива, даты
и ID самих связей не учитываются. Изменение состава/долей или схемы извне
вызывает `StreamPublicationConflictError` и не перезаписывается.
Независимые настройки (например, фильтры) не включаются в PUT и сохраняются
в новом снимке из ответа Keitaro. Для потока прямого редиректа Push запрещён.

Перед отправкой проверяются уникальность офферов, диапазон долей 0–100
и сумма 100% у непустого активного состава. Пустой состав разрешён:
`offers: []` очищает привязки. Архив и `is_pinned` остаются локальными.
Пересчёт долей при Push не выполняется — отправляются значения черновика.

После подтверждённого результата создаётся новый снимок, обновляется
`base_editor_state`, revision повышается. Последующий Cancel не возвращает
состояние до публикации, а локальный архив остаётся доступным для Restore.

PostgreSQL и Keitaro не имеют общей транзакции. При сбое после успешного PUT
локальный черновик остаётся неопубликованным. Повторный Push с той же версией
сначала читает Keitaro: если привязки уже совпадают с целью, PUT не повторяется,
а локальная фиксация завершается. Если локальный commit уже прошёл, но клиент
потерял ответ, старая revision получит конфликт; нужно перечитать черновик.
Несовпадение ответа PUT с целевым составом вызывает `StreamPublicationError`.

Проверка внешних изменений выполняется перед PUT. Без условных обновлений
со стороны Admin API она не исключает правку из админки в промежутке GET–PUT.
Локальные Fetch/Push и операции редактора защищены блокировками и revision.
Сетевые таймауты ограничивают время удержания локальных блокировок.

## Репозитории и транзакции

`AsyncDatabaseSessionManager` создаётся явно из `get_settings().db.url`.
Он предоставляет фабрику независимых сессий и `shutdown()` для закрытия пула.
При импорте модулей настройки не читаются и соединения не создаются.

`StreamUnitOfWorkSQLAlchemy(manager)` реализует ABC `StreamUnitOfWork`
и предоставляет `streams`, `snapshots`, `drafts`, `creations` в одной сессии.
Блокировки выполняют репозитории: `uow.creations.lock(request_id)` защищает
этап создания, `uow.streams.lock_campaign(campaign_id)` сериализует Fetch/Push.
Они действуют до commit/rollback общей транзакции; UOW управляет её жизненным
циклом и предоставляет репозитории:

```python
async with StreamUnitOfWorkSQLAlchemy(manager) as uow:
    service = StreamDraftService(uow.drafts, keitaro)
    draft = await service.remove_offer(draft_id, offer_id, expected_revision=revision)
    await uow.commit()
```

Commit всегда явный. Выход из блока, в том числе успешный, откатывает оставшиеся
незафиксированные изменения и закрывает сессию. После выхода репозитории
недоступны; повторно открыть тот же объект UOW можно, вложенный вход запрещён.

Сохранение черновика проверяет `revision` одним SQL UPDATE. При конфликте
возвращается `None`; сервис превращает его в `StreamDraftConflictError`.
Версия и состав черновика читаются одним SELECT. Запись заголовка и замена
офферов защищены savepoint: ошибка строки не оставляет частично записанный
черновик, даже если вызывающий код поймал исключение и продолжил транзакцию.
Архивные строки сохраняются, если они присутствуют в переданном DTO.

## Проверки

### Создание кампании

`CampaignCreationService.create_campaign(CreateCampaignDTO(...))` принимает
название, ISO-код страны, ID оффера и UUID `request_id`. Код страны нормализуется
и проверяется через `pycountry`. UUID создаёт вызывающий код один раз на действие
пользователя и сохраняет для повторов.

Домен, группа и источник выбираются из существующих справочников Keitaro.
В `.env` добавьте настройки (ID текущего тестового эмулятора):

```dotenv
CAMPAIGN_CREATION__DOMAIN_ID=1813
CAMPAIGN_CREATION__GROUP_ID=10332
CAMPAIGN_CREATION__TRAFFIC_SOURCE_ID=836
```

```python
from uuid import uuid4

from src.config import get_settings
from src.core.dto import CreateCampaignDTO
from src.core.services import CampaignCreationService
from src.infrastructure.database import AsyncDatabaseSessionManager
from src.infrastructure.database.uow import StreamUnitOfWorkSQLAlchemy
from src.infrastructure.keitaro import HttpKeitaroGateway


async def create_example():
    settings = get_settings()
    manager = AsyncDatabaseSessionManager(settings.db.url)
    try:
        async with HttpKeitaroGateway(settings.keitaro) as gateway:
            service = CampaignCreationService(
                lambda: StreamUnitOfWorkSQLAlchemy(manager),
                gateway,
                settings.campaign_creation,
            )
            return await service.create_campaign(CreateCampaignDTO(
                request_id=uuid4(), name="[TEST] Adrobot", country_code="AU",
                offer_id=18003,
            ))
    finally:
        await manager.shutdown()
```

Сервис проверяет оффер и справочники, создаёт выключенную кампанию с ротацией
по позиции, затем два включённых потока:

- `GEO`: обычный, принимает указанную страну, HTTP-редирект на Google;
- `Offers`: замыкающий, выбранный оффер получает 100%, фильтров нет.

После проверки обоих потоков кампания включается, а Fetch создаёт локальные
снимки и чистые черновики. Результат содержит внешние ID кампании и потоков.
Создатель и завершающий Fetch используют одну сессию для локальной фиксации.

Миграция `0002` добавляет `campaign_creation_attempts`: исходный запрос,
зафиксированные настройки, этап и внешние ID. `get_attempt(request_id)` позволяет
узнать сохранённый этап. Каждый этап сохраняется отдельным commit. Один UUID
с другими параметрами вызывает `CampaignCreationConflictError`; изменение
настроек `.env` не меняет ранее начатую операцию.

Повтор после таймаута/сбоя БД сверяет кампанию по стабильному alias
`adrobot-<UUID>`, потоки — по имени и настройкам, затем продолжает создание.
Уже завершённый запрос возвращает сохранённые ID без повторного создания.
Несовпадение настроек вызывает конфликт, чужие правки не перезаписываются.
Локальные параллельные запросы сериализуются блокировкой PostgreSQL.
Admin API не даёт общей транзакции с нашей БД: незавершённые объекты не удаляются
автоматически. Если включение прошло, а финальный Fetch завершился ошибкой,
кампания остаётся включённой, повтор заканчивает локальный импорт.
При неопределённом результате POST восстановление опирается на видимость
созданных объектов в API; это не серверный механизм идемпотентности Keitaro.

Сервисы пока вызываются из Python. HTTP-маршруты и подключение к FastAPI —
следующий этап.

### Живая проверка

Скрипт запускается только явно. Он читает ключ из `.env`, создаёт отдельную
кампанию `[TEST] Adrobot service verification`, проверяет создание, повтор,
Fetch, Add, Pin, Push, Cancel, Unpin, Remove и повторный Push. GEO не меняется.
В конце тестовая кампания выключается и остаётся в Keitaro для просмотра.
Локальная случайная схема удаляется; рабочая база не используется.

```powershell
$env:TEST_DATABASE_URL = 'postgresql+asyncpg://postgres@127.0.0.1:55479/adrobot_test'
uv run python -m scripts.verify_keitaro --live --domain-id 1813 --group-id 10332 --source-id 836 --offer-id 18003 --additional-offer-id 18001
```

### Автоматические проверки

```powershell
uv run pytest -q
uv run ruff check src tests alembic scripts
uv run ruff format --check src tests alembic scripts
```

Интеграционные тесты требуют отдельную пустую PostgreSQL-базу
с именем, начинающимся на `adrobot_test`; без URL они пропускаются:

```powershell
$env:TEST_DATABASE_URL = 'postgresql+asyncpg://postgres@127.0.0.1:5432/adrobot_test'
uv run pytest -q
```

Тесты миграции откатывают схему внутри транзакций. Тесты репозиториев/UOW
создают собственную случайную схему для проверки commit и конкурентных
соединений, затем удаляют только её. Рабочую базу им передавать нельзя.

# Adrobot


Реализованы DTO, ABC-контракты репозиториев и Keitaro, пересчёт долей,
SQLAlchemy-модели, первая миграция, SQL-репозитории, UnitOfWork и сервис
локального редактора черновиков. HTTP-адаптер Keitaro и API пока не реализованы.

## Зависимости

```powershell
uv sync
```

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

## Репозитории и транзакции

`AsyncDatabaseSessionManager` создаётся явно из `get_settings().db.url`.
Он предоставляет фабрику независимых сессий и `shutdown()` для закрытия пула.
При импорте модулей настройки не читаются и соединения не создаются.

`StreamUnitOfWorkSQLAlchemy(manager)` реализует ABC `StreamUnitOfWork`
и предоставляет `streams`, `snapshots`, `drafts` в одной сессии:

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

```powershell
uv run pytest -q
uv run ruff check src tests alembic
uv run ruff format --check src tests alembic
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

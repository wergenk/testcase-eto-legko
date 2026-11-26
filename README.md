# Adrobot

## Запуск через Docker Compose

Нужны Docker и Docker Compose.

1. Создайте `.env` из примера. Если `.env` уже существует, дополните его
   недостающими настройками.

   ```powershell
   Copy-Item .env.example .env
   ```

2. В `.env` задайте `KEITARO__BASE_URL`, `KEITARO__API_KEY`, а также ID домена,
   группы и источника из Keitaro:

   ```dotenv
   CAMPAIGN_CREATION__DOMAIN_ID=1813
   CAMPAIGN_CREATION__GROUP_ID=10332
   CAMPAIGN_CREATION__TRAFFIC_SOURCE_ID=836
   ```

   Значения ID выше относятся к тестовому серверу. `DB__URL` должен указывать
   на сервис PostgreSQL из Compose и соответствовать `POSTGRES_*`:

   ```dotenv
   DB__URL=postgresql+asyncpg://adrobot:change-me@postgres:5432/adrobot
   ```

3. Запустите PostgreSQL, примените миграции и запустите API:

   ```powershell
   docker compose up -d postgres
   docker compose run --rm --build --no-deps api uv run --no-sync alembic upgrade head
   docker compose up -d api
   ```

Документация API: [http://localhost:8000/docs](http://localhost:8000/docs).
Проверка запуска: [http://localhost:8000/health](http://localhost:8000/health).

Остановка:

```powershell
docker compose down
```

## Локальный запуск

Нужны Python 3.12+, uv и PostgreSQL.
Заполните `.env`, как описано выше. Для `DB__URL` укажите адрес доступной
PostgreSQL, например `127.0.0.1` вместо имени сервиса `postgres`.

```powershell
uv sync
uv run alembic upgrade head
uv run uvicorn src.api.create_app:create_app --factory --reload
```

Документация API: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs).

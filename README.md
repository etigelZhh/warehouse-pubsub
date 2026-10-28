# Склад с pub/sub

Два асинхронных сервиса для складских операций:

- **inventory_api** — HTTP API на aiohttp: принимает поступления и расходы, считает остатки и аналитику, публикует события в Redis.
- **analytics_worker** — подписчик Redis pub/sub: валидирует события и обновляет агрегированные остатки в таблице `stock_agg`.

Хранилище — PostgreSQL. Все запросы написаны на SQLAlchemy Core (без ORM) поверх asyncpg.

```
POST /receipts ─┐                      ┌─────────────────────┐
POST /issues   ─┼─► inventory_api ──► stock_events (PostgreSQL)
GET  /stock    ─┘        │
                         │ PUBLISH inventory.receipt / inventory.issue
                         ▼
                      Redis ──► analytics_worker ──► stock_agg (UPSERT)
```

## Структура

```
common/             общий код: конфиг, engine, таблицы, схемы событий
inventory_api/      сервис 1 (aiohttp)
analytics_worker/   сервис 2 (подписчик Redis)
migrations/         миграции Alembic
tests/              тесты на реальной БД и Redis
```

## Запуск

Нужен Docker с Compose.

```bash
docker compose up --build
```

Поднимутся `postgres`, `redis`, затем одноразовый сервис `migrate` (`alembic upgrade head`),
и после него `inventory_api` (порт 8080) и `analytics_worker`.

Если порты 5432/6379/8080 на машине заняты, их можно поменять:
`POSTGRES_PORT=5433 REDIS_PORT=6380 API_HOST_PORT=8081 docker compose up --build`
(тогда и в локальных `DATABASE_URL`/`TEST_DATABASE_URL` укажите новый порт).

### Миграции

В Docker миграции применяются автоматически сервисом `migrate`. Вручную:

```bash
docker compose run --rm migrate                 # внутри Docker
# или локально:
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/inventory alembic upgrade head
```

Откат: `alembic downgrade base`.

### Локальный запуск без Docker для сервисов

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
docker compose up -d postgres redis
alembic upgrade head
python -m inventory_api        # http://localhost:8080
python -m analytics_worker     # в соседнем терминале
```

Переменные окружения: `DATABASE_URL`, `REDIS_URL`, `API_HOST`, `API_PORT` (значения по умолчанию — в `common/config.py`).

## API

```bash
# поступление
curl -X POST localhost:8080/receipts -H 'Content-Type: application/json' \
     -d '{"sku": "A-100", "qty": 50, "warehouse": "WH-1"}'

# расход (409, если на складе не хватает товара)
curl -X POST localhost:8080/issues -H 'Content-Type: application/json' \
     -d '{"sku": "A-100", "qty": 20, "warehouse": "WH-1"}'

# остатки склада (sku — необязательный фильтр)
curl 'localhost:8080/stock?warehouse=WH-1'
curl 'localhost:8080/stock?warehouse=WH-1&sku=A-100'

# сводка, top_n — размер списка top_skus (по умолчанию 5)
curl 'localhost:8080/stock/summary?top_n=3'
```

Пример ответа `/stock/summary`:

```json
{
  "warehouses": [{"warehouse": "WH-1", "total_qty": 30, "sku_count": 1}],
  "top_skus": [{"sku": "A-100", "total_qty": 30}]
}
```

`sku_count` — число SKU с положительным остатком на складе.

Проверить, что воркер обновил агрегат:

```bash
docker compose exec postgres psql -U postgres -d inventory -c 'SELECT * FROM stock_agg'
```

## Как это устроено

**Таблицы**

- `stock_events` — журнал операций (`event_id`, `type` = receipt|issue, `sku`, `warehouse`, `qty > 0`, `created_at`).
- `stock_agg` — один остаток на пару `(warehouse, sku)` (первичный ключ).

**inventory_api**

- Операция пишется в `stock_events`; событие публикуется в Redis только после коммита.
- Для расхода берётся `pg_advisory_xact_lock` по паре склад+SKU, затем проверяется остаток,
  чтобы параллельные запросы не увели его в минус.
- `GET /stock` — `SUM(CASE ...)` с `GROUP BY sku` по журналу.
- `GET /stock/summary` — подзапрос с остатками по `(warehouse, sku)` (`GROUP BY`),
  поверх него два запроса с `GROUP BY warehouse` и `GROUP BY sku ... ORDER BY ... LIMIT top_n`.

**analytics_worker**

- Подписка на `inventory.receipt` и `inventory.issue`.
- Каждое сообщение проверяется pydantic-схемой; тип события должен совпадать с каналом.
  Некорректные сообщения логируются и пропускаются.
- Остаток обновляется одним запросом
  `INSERT ... ON CONFLICT (warehouse, sku) DO UPDATE SET qty = stock_agg.qty + EXCLUDED.qty`,
  поэтому на каждую пару всегда одна строка.
- Корректно завершается по SIGINT/SIGTERM.

**Ограничения.** Redis pub/sub не хранит сообщения: если воркер не запущен, события пропадут,
и `stock_agg` разойдётся с `stock_events`. Для гарантированной доставки можно перейти на
Redis Streams с consumer group (`XREADGROUP` + `XACK`) и хранить обработанные `event_id`
для идемпотентности.

## Тесты

Тесты работают с настоящими PostgreSQL (база `inventory_test`, создаётся при первом старте контейнера)
и Redis.

```bash
docker compose up -d postgres redis
docker compose run --rm tests
```

Или локально (после `pip install -r requirements-dev.txt`):

```bash
pytest -v
```

Что проверяется:

- поступление и расход меняют остаток; фильтр по SKU; 409 при нехватке; 400 на плохой ввод;
- `/stock/summary` и `top_n`;
- API публикует событие в Redis;
- воркер обновляет одну строку в `stock_agg` и пропускает некорректные сообщения;
- сквозной сценарий: POST в API → событие в Redis → воркер → `stock_agg`.

> Если база `inventory_test` не создалась (например, volume Postgres уже существовал), создайте её вручную:
> `docker compose exec postgres createdb -U postgres inventory_test`.

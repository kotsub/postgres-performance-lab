# PostgreSQL performance lab

Учебный стенд: сравнить один и тот же SELECT без дополнительного индекса и
с покрывающим индексом, затем посмотреть влияние числа одновременных клиентов.

**Статус проверки:** 6 тестов расчета метрик и обработки ошибок выполнены.
Docker-сборка и интеграционный прогон PostgreSQL в окружении подготовки
не выполнялись: Docker, psql и pgbench отсутствуют. Поэтому чисел TPS или
ускорения PostgreSQL в этом репозитории пока нет.
GitHub Actions настроен на короткий интеграционный запуск после публикации.

## Что внутри

- PostgreSQL 17 и отдельный контейнер с Python, psql и pgbench.
- Детерминированная генерация таблицы заказов.
- Два сценария: baseline без вторичного индекса и indexed с индексом
  (customer_id, created_at) INCLUDE (amount_cents).
- Клиенты 1, 4 и 8; по 3 повтора; прогрев перед каждым измерением.
- Чередование порядка baseline/indexed между повторами.
- TPS, средняя задержка, p50/p95/p99 из журналов отдельных транзакций.
- EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON), снимки счетчиков базы и сырой CSV.
- Проверка, что индекс не изменил результаты контрольных запросов.

Это стенд обычного PostgreSQL, а не бенчмарк Arenadata DB или MPP-кластера.

## Быстрый запуск через Docker Compose

Из корня репозитория; нужны установленный Docker и Docker Compose v2.

~~~bash
docker compose build lab
docker compose up -d --wait db
docker compose run --rm lab python3 -m unittest discover -s tests -v
docker compose run --rm lab python3 scripts/run_benchmark.py --reset-data
~~~

Полный эксперимент по умолчанию занимает несколько минут с учетом подготовки
и прогрева. Результаты сохраняются в новом каталоге results/<дата-UTC>/:

- REPORT.md - сводная таблица и ограничения;
- summary.csv - каждая комбинация сценария, числа клиентов и повтора;
- environment.json - версии и параметры;
- подкаталоги прогонов - планы EXPLAIN, вывод pgbench, все журналы транзакций,
  снимки pg_stat_database.

Короткая проверка перед большим запуском:

~~~bash
docker compose run --rm lab python3 scripts/run_benchmark.py --reset-data --rows 3000 --customers 100 --clients 1 2 --seconds 1 --repeats 1 --warmup 0
~~~

--reset-data явно разрешает пересоздать только таблицу perf_lab.orders
в тестовой базе. Используйте выделенную базу стенда, а не рабочую БД.
Данные базы хранятся в отдельном Docker volume; результаты - в папке проекта.
База на хосте доступна только через 127.0.0.1:55432.
Пароль lab-only-password предназначен исключительно для локального стенда.

Остановка:

~~~bash
docker compose down
~~~

## Запуск без Docker

Нужны Python 3.10+, сервер PostgreSQL и утилиты psql/pgbench версии 17.
Внешних Python-зависимостей нет.

~~~bash
export PGHOST=127.0.0.1
export PGPORT=55432
export PGUSER=bench
export PGDATABASE=perf_lab
# PGPASSWORD или .pgpass задаются отдельно и не коммитятся
python3 scripts/run_benchmark.py --reset-data
~~~

Параметры сервера такого запуска записываются в environment.json. Они могут
отличаться от Compose, и это нужно учитывать при сравнении.

## Методика и ограничения

См. docs/METHODOLOGY.md. Перед собеседованием пройдите docs/INTERVIEW_NOTES.md.
Тесты парсера содержат явно помеченные искусственные примеры формата вывода.
Они не являются измерениями производительности базы.

## Документация

- [pgbench 17](https://www.postgresql.org/docs/17/pgbench.html)
- [EXPLAIN](https://www.postgresql.org/docs/17/sql-explain.html)
- [Docker Compose services](https://docs.docker.com/reference/compose-file/services/)

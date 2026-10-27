"""Measure the same read-only workload with/without a secondary index."""

import argparse
import csv
import json
import os
import platform
import shutil
import statistics
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from metrics import parse_pgbench, percentile, read_latencies

ROOT = Path(__file__).resolve().parents[1]
INDEX_NAME = "perf_lab.orders_customer_date_idx"
SCENARIOS = ["baseline", "indexed"]


def positive_int(value):
    value = int(value)
    if value < 1:
        raise argparse.ArgumentTypeError("expected a positive integer")
    return value


def execute(command, env):
    completed = subprocess.run(
        command, env=env, text=True, capture_output=True, timeout=600, check=False
    )
    if completed.returncode:
        raise RuntimeError(
            f"{Path(command[0]).name} failed ({completed.returncode}): {completed.stderr.strip()}"
        )
    return completed.stdout


def psql(env, sql):
    return execute(["psql", "-X", "-A", "-t", "-v", "ON_ERROR_STOP=1", "-c", sql], env).strip()


def configure_scenario(env, scenario):
    psql(env, f"DROP INDEX IF EXISTS {INDEX_NAME};")
    if scenario == "indexed":
        psql(
            env,
            "CREATE INDEX orders_customer_date_idx ON perf_lab.orders "
            "(customer_id, created_at) INCLUDE (amount_cents);",
        )
    psql(env, "VACUUM (ANALYZE) perf_lab.orders;")


def reference_query(customer):
    return (
        "SELECT COALESCE(SUM(amount_cents), 0) FROM perf_lab.orders "
        f"WHERE customer_id = {customer} AND created_at >= DATE '2025-06-01';"
    )


def report(output, records):
    lines = [
        "# PostgreSQL: отчет измерений",
        "",
        "Сырые результаты каждого прогона: summary.csv. Параметры: environment.json.",
        "Время подготовки данных, создания индекса и прогрева исключено из замеров.",
        "p50/p95/p99 рассчитаны методом nearest rank из полных журналов транзакций.",
        "",
        "| Сценарий | Клиентов | Повторов | Медиана TPS | Медиана среднего времени, мс | Медиана p95, мс |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for scenario in SCENARIOS:
        for clients in sorted({row["clients"] for row in records}):
            group = [r for r in records if r["scenario"] == scenario and r["clients"] == clients]
            lines.append(
                f"| {scenario} | {clients} | {len(group)} | "
                f"{statistics.median(r['tps'] for r in group):.2f} | "
                f"{statistics.median(r['avg_ms'] for r in group):.3f} | "
                f"{statistics.median(r['p95_ms'] for r in group):.3f} |"
            )
    lines += [
        "",
        "## Как интерпретировать",
        "",
        "Сравнивайте сценарии при одинаковом количестве клиентов. Посмотрите планы "
        "EXPLAIN в каталогах прогонов: поменялся ли способ чтения таблицы? "
        "Увеличение числа клиентов может повысить TPS и одновременно ухудшить p95. "
        "Причины нужно подтверждать планами и метриками, а не только итоговым ускорением.",
        "",
        "## Ограничения",
        "",
        "Синтетическая read-only нагрузка на одном PostgreSQL. Это не измерение ADB "
        "или MPP-кластера. Режим закрытой нагрузки: каждый клиент ждет ответ перед "
        "следующим запросом; фиксированная внешняя интенсивность поступления запросов "
        "не моделируется. Поэтому процентили не описывают задержки при произвольной "
        "внешней очереди. Логирование влияет на оба сценария. Перед каждым прогоном есть "
        "прогрев, но холодный кэш не гарантируется. Системные счетчики pg_stat_database "
        "обновляются с задержкой и пригодны только как дополнительный контекст. "
        "Таблица выше содержит медианы отдельных прогонов, а не объединенные процентили.",
    ]
    (output / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=positive_int, default=200_000)
    parser.add_argument("--customers", type=positive_int, default=10_000)
    parser.add_argument("--clients", nargs="+", type=positive_int, default=[1, 4, 8])
    parser.add_argument("--seconds", type=positive_int, default=5)
    parser.add_argument("--repeats", type=positive_int, default=3)
    parser.add_argument("--warmup", type=int, default=2)
    parser.add_argument("--reset-data", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.rows < args.customers or args.warmup < 0:
        parser.error("rows must be >= customers; warmup must be >= 0")
    if not args.reset_data:
        parser.error("--reset-data is required; this replaces only perf_lab.orders in the test database")
    missing = [name for name in ("psql", "pgbench") if shutil.which(name) is None]
    if missing:
        parser.error("missing executables: " + ", ".join(missing) + "; use Docker Compose")
    env = os.environ.copy()
    for key, value in {
        "PGHOST": "127.0.0.1", "PGPORT": "55432", "PGUSER": "bench",
        "PGPASSWORD": "lab-only-password", "PGDATABASE": "perf_lab", "PGCONNECT_TIMEOUT": "10",
    }.items():
        env.setdefault(key, value)
    env["LC_ALL"] = "C"
    # Record only non-secret connection context; never serialize the complete env.
    server_version = psql(env, "SHOW server_version;")
    output = args.output or ROOT / "results" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    execute(
        ["psql", "-X", "-v", "ON_ERROR_STOP=1", "-v", f"rows={args.rows}",
         "-v", f"customers={args.customers}", "-f", str(ROOT / "sql/prepare.sql")],
        env,
    )
    metadata = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "server_version": server_version,
        "pgbench_version": execute(["pgbench", "--version"], env).strip(),
        "python": platform.python_version(),
        "rows": args.rows, "customers": args.customers,
        "clients": list(dict.fromkeys(args.clients)),
        "seconds": args.seconds, "repeats": args.repeats, "warmup_seconds": args.warmup,
        "shared_buffers": psql(env, "SHOW shared_buffers;"),
        "max_parallel_workers_per_gather": psql(env, "SHOW max_parallel_workers_per_gather;"),
        "jit": psql(env, "SHOW jit;"),
        "logging": "all transactions; includes instrumentation overhead",
    }
    (output / "environment.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    probe_customers = sorted({1, max(1, args.customers // 2), args.customers})
    reference = [psql(env, reference_query(customer)) for customer in probe_customers]
    records = []
    snapshot_sql = (
        "SELECT row_to_json(s) FROM (SELECT numbackends, xact_commit, xact_rollback, "
        "blks_read, blks_hit, temp_bytes, deadlocks FROM pg_stat_database "
        "WHERE datname = current_database()) s;"
    )
    for repeat in range(1, args.repeats + 1):
        for clients in metadata["clients"]:
            scenarios = SCENARIOS if repeat % 2 else list(reversed(SCENARIOS))
            for scenario in scenarios:
                run = output / f"{scenario}_c{clients}_r{repeat}"
                run.mkdir()
                configure_scenario(env, scenario)
                actual = [psql(env, reference_query(customer)) for customer in probe_customers]
                if actual != reference:
                    raise AssertionError("index changed query results")
                base = [
                    "pgbench", "--random-seed", str(42 + repeat), "-n", "-M", "prepared",
                    "-c", str(clients), "-j", str(min(clients, 4)),
                    "--exit-on-abort", "-D", f"customers={args.customers}",
                    "-f", str(ROOT / "sql/workload.sql"),
                ]
                if args.warmup:
                    execute(base + ["-T", str(args.warmup)], env)
                plan = psql(
                    env, "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + reference_query(1)
                )
                (run / "explain.json").write_text(plan + "\n", encoding="utf-8")
                before = json.loads(psql(env, snapshot_sql))
                text = execute(
                    base + ["-T", str(args.seconds), "-l", "--log-prefix", str(run / "transactions")],
                    env,
                )
                (run / "pgbench.txt").write_text(text, encoding="utf-8")
                snapshots = {"before": before, "after": json.loads(psql(env, snapshot_sql))}
                (run / "db_stats.json").write_text(json.dumps(snapshots, indent=2) + "\n")
                values = parse_pgbench(text)
                samples = read_latencies(sorted(run.glob("transactions.*")))
                if len(samples) != values["transactions"]:
                    raise ValueError("incomplete transaction logs; cannot calculate valid percentiles")
                values.update(
                    scenario=scenario, clients=clients, repeat=repeat,
                    p50_ms=percentile(samples, .5), p95_ms=percentile(samples, .95),
                    p99_ms=percentile(samples, .99),
                )
                records.append(values)
                with (output / "summary.csv").open("w", newline="", encoding="utf-8") as stream:
                    writer = csv.DictWriter(stream, fieldnames=list(records[0]))
                    writer.writeheader()
                    writer.writerows(records)
                print(f"{scenario}, clients={clients}, repeat={repeat}: TPS={values['tps']:.2f}")
    report(output, records)
    print(f"Report: {output / 'REPORT.md'}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, ValueError, AssertionError) as error:
        raise SystemExit(str(error)) from error

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("metrics", ROOT / "scripts/metrics.py")
metrics = importlib.util.module_from_spec(spec)
spec.loader.exec_module(metrics)

# Representative parser fixture, NOT a measured benchmark result.
EXAMPLE_OUTPUT = """number of transactions actually processed: 100/100
number of failed transactions: 0 (0.000%)
latency average = 2.500 ms
tps = 400.000 (without initial connection time)
"""


class MetricsTests(unittest.TestCase):
    def test_standard_and_time_limited_output(self):
        for text in [EXAMPLE_OUTPUT, EXAMPLE_OUTPUT.replace("100/100", "100")]:
            result = metrics.parse_pgbench(text)
            self.assertEqual(result["transactions"], 100)
            self.assertEqual(result["avg_ms"], 2.5)
            self.assertEqual(result["tps"], 400)

    def test_failed_or_incomplete_output_is_not_a_success(self):
        for text in [
            EXAMPLE_OUTPUT.replace("transactions: 0", "transactions: 2"),
            EXAMPLE_OUTPUT.replace("100/100", "0/100"),
            "connection failed",
        ]:
            with self.assertRaises(ValueError):
                metrics.parse_pgbench(text)

    def test_percentiles_combine_workers_and_convert_microseconds(self):
        with tempfile.TemporaryDirectory() as directory:
            first, second = Path(directory) / "log.1", Path(directory) / "log.2"
            first.write_text("0 1 1000 0 123 0\n0 2 3000 0 123 0\n")
            second.write_text("1 1 2000 0 123 0\n1 2 4000 0 123 0\n")
            values = metrics.read_latencies([first, second])
            self.assertEqual(values, [1, 2, 3, 4])
            self.assertEqual(metrics.percentile(values, .5), 2)
            self.assertEqual(metrics.percentile(values, .95), 4)

    def test_empty_bad_and_failed_logs_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "log"
            for text in ["", "0 1\n", "0 1 failed 0 123 0\n", "0 1 -2 0 123 0\n"]:
                log.write_text(text)
                with self.assertRaises(ValueError):
                    metrics.read_latencies([log])

    def test_percentiles_require_samples_and_valid_fraction(self):
        for values, fraction in [([], .95), ([1], 0), ([1], 1.1)]:
            with self.assertRaises(ValueError):
                metrics.percentile(values, fraction)

    def test_cli_requires_explicit_data_reset(self):
        completed = subprocess.run(
            [sys.executable, str(ROOT / "scripts/run_benchmark.py")],
            capture_output=True, text=True, check=False,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("--reset-data is required", completed.stderr)


if __name__ == "__main__":
    unittest.main()

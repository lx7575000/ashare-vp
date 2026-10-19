from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, time
from pathlib import Path
from unittest import mock

from ashare_vp.quotes import TZ
from ashare_vp.scheduler import (
    _execute,
    _is_trading_day,
    _missed,
    build_parser,
    next_run,
    parse_times,
)


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.times = [time(11, 0), time(14, 0)]

    def test_next_run_morning(self):
        now = datetime(2026, 10, 16, 10, 0, tzinfo=TZ)  # Friday
        target = next_run(now, self.times)
        self.assertEqual(target, datetime(2026, 10, 16, 11, 0, tzinfo=TZ))

    def test_next_run_after_morning(self):
        now = datetime(2026, 10, 16, 12, 0, tzinfo=TZ)
        target = next_run(now, self.times)
        self.assertEqual(target, datetime(2026, 10, 16, 14, 0, tzinfo=TZ))

    def test_next_run_weekend(self):
        now = datetime(2026, 10, 16, 15, 0, tzinfo=TZ)  # Friday after close
        target = next_run(now, self.times)
        self.assertEqual(target, datetime(2026, 10, 19, 11, 0, tzinfo=TZ))

    def test_next_run_at_exact_time_goes_next(self):
        now = datetime(2026, 10, 16, 11, 0, tzinfo=TZ)
        target = next_run(now, self.times)
        self.assertEqual(target, datetime(2026, 10, 16, 14, 0, tzinfo=TZ))

    def test_parse_times(self):
        self.assertEqual(parse_times("11:00, 14:00"), [time(11, 0), time(14, 0)])
        with self.assertRaises(ValueError):
            parse_times("bad")
        with self.assertRaises(ValueError):
            parse_times("")

    def test_is_trading_day(self):
        self.assertTrue(_is_trading_day(datetime(2026, 10, 16, 11, 0, tzinfo=TZ)))
        self.assertFalse(_is_trading_day(datetime(2026, 10, 17, 11, 0, tzinfo=TZ)))

    def test_missed_slot(self):
        target = datetime(2026, 10, 16, 11, 0, tzinfo=TZ)
        self.assertFalse(_missed(target, datetime(2026, 10, 16, 11, 29, tzinfo=TZ), 30))
        self.assertTrue(_missed(target, datetime(2026, 10, 16, 11, 31, tzinfo=TZ), 30))
        self.assertFalse(_missed(target, datetime(2026, 10, 16, 16, 0, tzinfo=TZ), 0))


class SchedulerExecuteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.config_path = self.root / "assets.json"
        self.config_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "settings": {
                        "start_date": "2025-01-01",
                        "min_bars": 30,
                        "source_order": ["tencent"],
                    },
                    "groups": [
                        {
                            "name": "测试ETF",
                            "kind": "etf",
                            "assets": [
                                {
                                    "code": "159999",
                                    "name": "测试ETF",
                                    "exchange": "SZ",
                                    "tencent": "sz159999",
                                }
                            ],
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        self.state_path = self.root / "state.json"

    def tearDown(self):
        self.tmp.cleanup()

    def make_args(self, *extra):
        return build_parser().parse_args(
            [
                "--config",
                str(self.config_path),
                "--cache-dir",
                str(self.root / "cache"),
                "--snapshot-dir",
                str(self.root / "snapshots"),
                "--output-dir",
                str(self.root / "reports"),
                "--state-file",
                str(self.state_path),
                "--quiet",
                *extra,
            ]
        )

    def run_execute(self, args, now, require_current=True):
        buffer = io.StringIO()
        with mock.patch("ashare_vp.scheduler.run_session", return_value=0) as runner:
            with redirect_stdout(buffer):
                code = _execute(args, now, require_current=require_current)
        return code, runner, buffer.getvalue()

    def test_execute_marks_state_and_skips_duplicate(self):
        args = self.make_args()
        now = datetime(2026, 10, 16, 11, 0, tzinfo=TZ)
        code, runner, _ = self.run_execute(args, now)
        self.assertEqual(code, 0)
        runner.assert_called_once()
        self.assertEqual(runner.call_args.kwargs["session"], "1100")
        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertIn("2026-10-16-1100", state["runs"])

        code, runner, _ = self.run_execute(args, now)
        self.assertEqual(code, 3)
        runner.assert_not_called()

    def test_execute_uses_actual_time_session(self):
        args = self.make_args()
        now = datetime(2026, 10, 16, 14, 5, tzinfo=TZ)
        code, runner, _ = self.run_execute(args, now)
        self.assertEqual(code, 0)
        self.assertEqual(runner.call_args.kwargs["session"], "1400")
        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertIn("2026-10-16-1400", state["runs"])

    def test_execute_skips_weekend(self):
        args = self.make_args()
        code, runner, output = self.run_execute(
            args, datetime(2026, 10, 17, 11, 0, tzinfo=TZ)
        )
        self.assertEqual(code, 3)
        runner.assert_not_called()
        self.assertIn("周末休市", output)

    def test_execute_skips_holiday(self):
        holiday = self.root / "holiday.json"
        holiday.write_text(json.dumps(["2026-10-16"]), encoding="utf-8")
        args = self.make_args("--holiday-file", str(holiday))
        code, runner, output = self.run_execute(
            args, datetime(2026, 10, 16, 11, 0, tzinfo=TZ)
        )
        self.assertEqual(code, 3)
        runner.assert_not_called()
        self.assertIn("休市", output)

    def test_force_weekend_runs_without_marking_state(self):
        args = self.make_args("--force")
        code, runner, _ = self.run_execute(
            args, datetime(2026, 10, 17, 11, 0, tzinfo=TZ), require_current=False
        )
        self.assertEqual(code, 0)
        runner.assert_called_once()
        self.assertFalse(self.state_path.exists())


if __name__ == "__main__":
    unittest.main()

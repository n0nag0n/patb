import unittest
from datetime import datetime

from patb.cronexpr import CronError, matches, parse


class CronTest(unittest.TestCase):
    def test_hourly(self):
        dt = datetime(2026, 8, 30, 10, 0)
        self.assertTrue(matches("@hourly", dt))
        self.assertFalse(matches("@hourly", datetime(2026, 8, 30, 10, 1)))

    def test_every_minute(self):
        self.assertTrue(matches("* * * * *", datetime(2026, 1, 1, 0, 17)))

    def test_step(self):
        self.assertTrue(matches("*/15 * * * *", datetime(2026, 1, 1, 0, 45)))
        self.assertFalse(matches("*/15 * * * *", datetime(2026, 1, 1, 0, 16)))

    def test_bad(self):
        with self.assertRaises(CronError):
            parse("not cron")
        with self.assertRaises(CronError):
            parse("0 0 0 0")


if __name__ == "__main__":
    unittest.main()

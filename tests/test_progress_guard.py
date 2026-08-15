from __future__ import annotations

import unittest

from utils.progress_guard import ProgressGuard


class ProgressGuardTests(unittest.TestCase):
    def test_progress_is_monotonic_and_reserves_completion(self) -> None:
        emitted: list[int] = []
        progress = ProgressGuard(emitted.append)

        for value in (5, 20, 15, 100, 99, 100):
            progress.update(value)

        self.assertEqual(emitted, [5, 20, 99])
        self.assertNotIn(100, emitted)

        progress.succeed()

        self.assertEqual(emitted, [5, 20, 99, 100])
        self.assertEqual(progress.value, 100)
        self.assertTrue(progress.terminal)

    def test_failure_prevents_success_completion(self) -> None:
        emitted: list[int] = []
        progress = ProgressGuard(emitted.append)

        progress.update(40)
        progress.fail()
        progress.update(80)
        progress.succeed()

        self.assertEqual(emitted, [40])
        self.assertEqual(progress.value, 40)
        self.assertTrue(progress.terminal)


if __name__ == "__main__":
    unittest.main()

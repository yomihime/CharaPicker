from __future__ import annotations

import unittest
from unittest.mock import patch

from utils.subprocess_utils import no_window_creation_flags


class NoWindowCreationFlagsTests(unittest.TestCase):
    def test_returns_create_no_window_on_windows(self) -> None:
        with (
            patch("utils.subprocess_utils.os.name", "nt"),
            patch("utils.subprocess_utils.subprocess.CREATE_NO_WINDOW", 0x08000000, create=True),
        ):
            self.assertEqual(no_window_creation_flags(), 0x08000000)

    def test_returns_zero_outside_windows(self) -> None:
        with patch("utils.subprocess_utils.os.name", "posix"):
            self.assertEqual(no_window_creation_flags(), 0)


if __name__ == "__main__":
    unittest.main()

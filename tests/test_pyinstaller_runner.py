from __future__ import annotations

import unittest

from scripts.run_pyinstaller_isolated import isolated_pyinstaller_path, pyinstaller_environment


class PyInstallerRunnerTests(unittest.TestCase):
    def test_host_path_is_not_inherited(self) -> None:
        environment = {
            "Path": r"C:\HostQt\bin;C:\HostPython;C:\UnexpectedTools",
            "SYSTEMROOT": r"C:\Windows",
        }

        child = pyinstaller_environment(
            environment,
            python_executable=r"E:\repo\.venv\Scripts\python.exe",
            base_executable=r"C:\Python312\python.exe",
            base_prefix=r"C:\Python312",
        )

        self.assertNotIn("HostQt", child["PATH"])
        self.assertNotIn("HostPython", child["PATH"])
        self.assertNotIn("UnexpectedTools", child["PATH"])
        self.assertIn(r"E:\repo\.venv\Scripts", child["PATH"])
        self.assertIn(r"C:\Python312", child["PATH"])
        self.assertIn(r"C:\Windows\System32", child["PATH"])
        self.assertNotIn("Path", child)

    def test_required_paths_are_deduplicated_case_insensitively(self) -> None:
        result = isolated_pyinstaller_path(
            {"SystemRoot": r"C:\Windows"},
            python_executable=r"C:\Python312\python.exe",
            base_executable=r"c:\python312\python.exe",
            base_prefix=r"C:\Python312",
        )

        entries = result.split(";")
        self.assertEqual(sum(entry.casefold() == r"c:\python312" for entry in entries), 1)


if __name__ == "__main__":
    unittest.main()

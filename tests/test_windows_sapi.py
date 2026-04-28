from __future__ import annotations

import unittest

from tts_service.adapters.synthesizers.windows_sapi import POWERSHELL_SCRIPT


class WindowsSapiTests(unittest.TestCase):
    def test_script_reads_input_text_as_utf8(self) -> None:
        self.assertIn("[System.Text.Encoding]::UTF8", POWERSHELL_SCRIPT)


if __name__ == "__main__":
    unittest.main()

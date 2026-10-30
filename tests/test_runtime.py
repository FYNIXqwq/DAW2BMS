import sys
import unittest
from unittest.mock import patch

from daw2bms.runtime import ableton_helper_command


class RuntimeTests(unittest.TestCase):
    def test_frozen_helper_reenters_bundle_without_python_module_switch(self):
        with patch.object(sys, 'frozen', True, create=True), patch.object(sys, 'executable', 'D:/portable app/DAW2BMS.exe'):
            self.assertEqual(ableton_helper_command(), ['D:/portable app/DAW2BMS.exe', '--ableton-ui'])

    def test_source_helper_still_uses_current_python(self):
        with patch.object(sys, 'frozen', False, create=True):
            self.assertEqual(ableton_helper_command(), [sys.executable, '-m', 'daw2bms.ableton_ui'])


if __name__ == '__main__':
    unittest.main()

# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2008-2026 Andrew Ziem.

"""Tests for toolkit-independent wx GUI behavior."""

import sys
import unittest
from unittest import mock

from bleachbit.GuiLauncher import run_gui, select_gui_toolkit
from bleachbit.WxGuiSupport import (
    CleanerOption, build_operations, cleaner_options)


class FakeBackend:
    """Minimal cleaner backend used by the support-layer tests."""

    def __init__(self, name, usable=True):
        self.name = name
        self.usable = usable
        self.options = {
            'cache': ('Cache', 'Delete cached files'),
            'danger': ('Dangerous', 'A guarded option'),
        }

    def get_name(self):
        return self.name

    def is_usable(self):
        return self.usable

    def get_options(self):
        return iter((('cache', 'Cache'), ('danger', 'Dangerous')))

    def get_warning(self, option_id):
        return 'High risk' if option_id == 'danger' else None


class WxGuiSupportTestCase(unittest.TestCase):
    """Verify model ordering and safety boundaries without importing wx."""

    def test_windows_defaults_to_wx_and_override_is_respected(self):
        self.assertEqual('wx', select_gui_toolkit('nt', {}))
        self.assertEqual('gtk', select_gui_toolkit('posix', {}))
        self.assertEqual(
            'gtk', select_gui_toolkit('nt', {'BLEACHBIT_GUI_TOOLKIT': 'gtk'}))

    def test_cleaner_options_are_flat_sorted_and_descriptive(self):
        rows = cleaner_options({
            'z': FakeBackend('Zulu'),
            'a': FakeBackend('Alpha'),
            'system': FakeBackend('System', usable=False),
            '_gui': FakeBackend('Temporary'),
            'unused': FakeBackend('Unused', usable=False),
        })
        self.assertEqual(
            ['Alpha', 'Alpha', 'System', 'System', 'Zulu', 'Zulu'],
                         [row.cleaner_name for row in rows])
        self.assertIn('Delete cached files', rows[0].accessible_label)
        self.assertIn('High risk', rows[1].accessible_label)

    def test_build_operations_rejects_warning_without_expert_mode(self):
        rows = [
            CleanerOption('system', 'cache', 'System', 'Cache', 'Safe'),
            CleanerOption('system', 'danger', 'System', 'Danger',
                          'Risky', 'High risk'),
            CleanerOption('browser', 'cache', 'Browser', 'Cache', 'Safe'),
        ]
        self.assertEqual(
            {'system': ['cache'], 'browser': ['cache']},
            build_operations(rows, [2, 1, 0, 999, -1], expert_mode=False))
        self.assertEqual(
            {'system': ['cache', 'danger'], 'browser': ['cache']},
            build_operations(rows, [2, 1, 0], expert_mode=True))

    @mock.patch('bleachbit.GuiLauncher.importlib.util.find_spec')
    def test_gui_availability_checks_wx_without_importing_gtk(self, find_spec):
        from bleachbit.GuiLauncher import is_gui_available
        find_spec.return_value = object()
        self.assertTrue(is_gui_available('nt', {}))
        find_spec.assert_called_once_with('wx')

    def test_run_gui_routes_to_wx_application(self):
        fake_module = mock.MagicMock()
        fake_app = fake_module.Bleachbit.return_value
        fake_app.run.return_value = 7
        with mock.patch('bleachbit.GuiLauncher.select_gui_toolkit',
                        return_value='wx'), \
                mock.patch.dict(sys.modules, {
                    'bleachbit.WxApplication': fake_module,
                }):
            result = run_gui(uac=False, shred_paths=['example'],
                             auto_exit=True, argv=['bleachbit'])
        self.assertEqual(7, result)
        fake_module.Bleachbit.assert_called_once_with(
            uac=False, shred_paths=['example'], auto_exit=True)
        fake_app.run.assert_called_once_with(['bleachbit'])


if __name__ == '__main__':
    unittest.main()

# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2008-2026 Andrew Ziem.

"""Windows runtime tests for the native accessible wx controls."""

import ctypes
import importlib.util
import unittest
from unittest import mock

from tests import common


WX_AVAILABLE = importlib.util.find_spec('wx') is not None


@common.skipUnlessWindows
@unittest.skipUnless(WX_AVAILABLE, 'wxPython is not installed')
class WxApplicationTestCase(unittest.TestCase):
    """Verify the controls exposed to NVDA are native and named."""

    @classmethod
    def setUpClass(cls):
        import wx
        cls.wx = wx
        cls.app = wx.App(False)

    @classmethod
    def tearDownClass(cls):
        cls.app.Destroy()

    @staticmethod
    def _window_class(control):
        buffer = ctypes.create_unicode_buffer(256)
        ctypes.windll.user32.GetClassNameW(
            control.GetHandle(), buffer, len(buffer))
        return buffer.value

    def test_main_controls_are_native_named_and_checkbox_enabled(self):
        from bleachbit.WxApplication import MainFrame

        with mock.patch.object(MainFrame, '_load_cleaners'):
            frame = MainFrame(self.app)
        try:
            self.assertEqual('SysListView32',
                             self._window_class(frame.option_list))
            self.assertTrue(frame.option_list.HasCheckBoxes())
            self.assertEqual('Cleaner options', frame.option_list.GetName())
            self.assertEqual('Preview', frame.preview_button.GetName())
            self.assertEqual('Clean', frame.clean_button.GetName())
            self.assertEqual('Abort', frame.abort_button.GetName())
            self.assertEqual('Activity log', frame.output.GetName())
            self.assertEqual('Operation progress', frame.progress.GetName())
        finally:
            frame.Close(force=True)
            self.wx.YieldIfNeeded()

    def test_preferences_use_native_accessible_lists_and_tabs(self):
        from bleachbit.WxApplication import MainFrame, PreferencesDialog

        with mock.patch.object(MainFrame, '_load_cleaners'):
            frame = MainFrame(self.app)
        try:
            with mock.patch('bleachbit.WxApplication.threading.Thread.start'):
                dialog = PreferencesDialog(frame)
            try:
                notebook = next(
                    child for child in dialog.GetChildren()
                    if isinstance(child, self.wx.Notebook))
                self.assertEqual(4, notebook.GetPageCount())
                self.assertEqual('_wx_SysTabCtl32',
                                 self._window_class(notebook))
                self.assertEqual(
                    'Custom cleaning paths',
                    dialog.custom_panel.path_list.GetName())
                self.assertEqual(
                    'Protected paths', dialog.keep_panel.path_list.GetName())
                self.assertEqual(
                    'Cookies to keep', dialog.cookie_panel.cookie_list.GetName())
                self.assertTrue(
                    dialog.cookie_panel.cookie_list.HasCheckBoxes())
            finally:
                dialog.Destroy()
        finally:
            frame.Close(force=True)
            self.wx.YieldIfNeeded()


if __name__ == '__main__':
    unittest.main()

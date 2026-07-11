# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Andrew Ziem
#
# This work is licensed under the terms of the GNU GPL, version 3 or
# later.  See the COPYING file in the top-level directory.

"""Tests for screen-reader accessibility helpers."""

import unittest
from unittest import mock

from bleachbit import Accessibility


class _Accessible:
    __gtype__ = object()

    def __init__(self):
        self.name = None
        self.description = None
        self.emissions = []

    def set_name(self, name):
        self.name = name

    def set_description(self, description):
        self.description = description

    def emit(self, *args):
        self.emissions.append(args)


class _Widget:
    def __init__(self):
        self.accessible = _Accessible()

    def get_accessible(self):
        return self.accessible


class _Label:
    def __init__(self, text):
        self.text = text
        self.mnemonic_widget = None

    def get_text(self):
        return self.text

    def set_mnemonic_widget(self, widget):
        self.mnemonic_widget = widget


class AccessibilityTestCase(unittest.TestCase):
    """Verify accessibility metadata and compatible live announcements."""

    def test_set_accessible_name_and_description(self):
        widget = _Widget()
        Accessibility.set_accessible_name(widget, 'Results', 'Operation log')
        self.assertEqual('Results', widget.accessible.name)
        self.assertEqual('Operation log', widget.accessible.description)

    def test_helpers_tolerate_missing_accessible_object(self):
        widget = mock.Mock()
        widget.get_accessible.return_value = None
        Accessibility.set_accessible_name(widget, 'Name')
        Accessibility.announce(widget, 'Done')
        Accessibility.set_accessible_name(None, 'Name')
        Accessibility.announce(object(), 'Done')

    def test_label_control_sets_relation_and_name(self):
        label = _Label('Language: ')
        control = _Widget()
        Accessibility.label_control(label, control)
        self.assertIs(control, label.mnemonic_widget)
        self.assertEqual('Language', control.accessible.name)

    @mock.patch.object(Accessibility, 'GObject')
    def test_announce_prefers_notification(self, gobject):
        widget = _Widget()
        gobject.signal_lookup.side_effect = lambda name, _gtype: {
            'notification': 1,
            'announcement': 2,
        }.get(name, 0)
        Accessibility.announce(widget, 'Cannot continue', assertive=True)
        self.assertEqual('Cannot continue', widget.accessible.name)
        self.assertEqual(
            [('notification', 'Cannot continue', 1)],
            widget.accessible.emissions)

    @mock.patch.object(Accessibility, 'GObject')
    def test_announce_falls_back_to_older_signal(self, gobject):
        widget = _Widget()
        gobject.signal_lookup.side_effect = lambda name, _gtype: int(
            name == 'announcement')
        Accessibility.announce(widget, 'Done')
        self.assertEqual([('announcement', 'Done')],
                         widget.accessible.emissions)

    @mock.patch.object(Accessibility, 'GObject')
    def test_broken_notification_bridge_falls_back_safely(self, gobject):
        widget = _Widget()
        gobject.signal_lookup.return_value = 1

        def emit(signal_name, *args):
            if signal_name == 'notification':
                raise TypeError('old bridge')
            widget.accessible.emissions.append((signal_name, *args))

        widget.accessible.emit = emit
        Accessibility.announce(widget, 'Done')
        self.assertEqual([('announcement', 'Done')],
                         widget.accessible.emissions)

    @mock.patch.object(Accessibility, 'GObject')
    def test_announce_name_change_supports_old_atk(self, gobject):
        widget = _Widget()
        gobject.signal_lookup.return_value = 0
        Accessibility.announce(widget, 'Done')
        self.assertEqual('Done', widget.accessible.name)
        self.assertEqual([], widget.accessible.emissions)

    def test_empty_announcement_is_ignored(self):
        widget = _Widget()
        Accessibility.announce(widget, '')
        self.assertIsNone(widget.accessible.name)


if __name__ == '__main__':
    unittest.main()

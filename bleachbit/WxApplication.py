# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2008-2026 Andrew Ziem.
#
# This work is licensed under the terms of the GNU GPL, version 3 or
# later.  See the COPYING file in the top-level directory.

"""Accessible native Windows frontend implemented with wxPython.

The controls in this module are backed by native Microsoft Windows widgets,
which expose their names, roles, states, and values to NVDA through the
Windows accessibility APIs.
"""

import json
import logging
import os
import sys
import threading
import time

import wx

import bleachbit
from bleachbit import APP_NAME, APP_VERSION, FileUtilities
from bleachbit.Cleaner import backends, create_simple_cleaner, register_cleaners
from bleachbit.Constant import (
    ABORT_BUTTON_LABEL, EMPTY_SPACE_WARNING, REQUIRES_EXPERT_MODE)
from bleachbit.Language import get_text as _
from bleachbit.Options import options
from bleachbit.WxGuiSupport import build_operations, cleaner_options

logger = logging.getLogger(__name__)


class _WxLogHandler(logging.Handler):
    """Copy application log messages into the native activity control."""

    def __init__(self, frame):
        super().__init__()
        self.frame = frame
        self.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))

    def emit(self, record):
        try:
            self.frame.append_text(self.format(record) + '\n',
                                   'error' if record.levelno >= logging.ERROR else None)
        except Exception:
            self.handleError(record)


class PathListPanel(wx.Panel):
    """Native editor for custom or protected file-system paths."""

    def __init__(self, parent, values, accessible_name, delete_paths=False,
                 expert_mode_getter=None):
        super().__init__(parent)
        self.delete_paths = delete_paths
        self.expert_mode_getter = expert_mode_getter or (
            lambda: options.get('expert_mode'))
        self.path_list = wx.ListCtrl(
            self, style=wx.LC_REPORT | wx.BORDER_SUNKEN)
        self.path_list.SetName(accessible_name)
        self.path_list.InsertColumn(0, _('Type'))
        self.path_list.InsertColumn(1, _('Path'))
        for path_type, path in values:
            self._append(path_type, path)
        self.path_list.SetColumnWidth(0, wx.LIST_AUTOSIZE_USEHEADER)
        self.path_list.SetColumnWidth(1, 420)

        add_file = wx.Button(self, label=_('Add &file…'))
        add_folder = wx.Button(self, label=_('Add f&older…'))
        remove = wx.Button(self, label=_('&Remove selected'))
        add_file.Bind(wx.EVT_BUTTON, self._on_add_file)
        add_folder.Bind(wx.EVT_BUTTON, self._on_add_folder)
        remove.Bind(wx.EVT_BUTTON, self._on_remove)

        buttons = wx.BoxSizer(wx.HORIZONTAL)
        buttons.Add(add_file, 0, wx.RIGHT, 8)
        buttons.Add(add_folder, 0, wx.RIGHT, 8)
        buttons.Add(remove)
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.path_list, 1, wx.EXPAND | wx.ALL, 10)
        sizer.Add(buttons, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        self.SetSizer(sizer)

    def _append(self, path_type, path):
        index = self.path_list.InsertItem(
            self.path_list.GetItemCount(),
            _('File') if path_type == 'file' else _('Folder'))
        self.path_list.SetItem(index, 1, path)
        self.path_list.SetItemData(index, 0 if path_type == 'file' else 1)

    def _on_add_file(self, _event):
        dialog = wx.FileDialog(
            self, message=_('Choose files'),
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST | wx.FD_MULTIPLE)
        try:
            if dialog.ShowModal() == wx.ID_OK:
                for path in dialog.GetPaths():
                    if self._validate_new_path(path):
                        self._append('file', path)
        finally:
            dialog.Destroy()

    def _on_add_folder(self, _event):
        dialog = wx.DirDialog(
            self, message=_('Choose a folder'), style=wx.DD_DIR_MUST_EXIST)
        try:
            if dialog.ShowModal() == wx.ID_OK:
                path = dialog.GetPath()
                if self._validate_new_path(path):
                    self._append('folder', path)
        finally:
            dialog.Destroy()

    def _on_remove(self, _event):
        selected = []
        index = self.path_list.GetFirstSelected()
        while index != -1:
            selected.append(index)
            index = self.path_list.GetNextSelected(index)
        for index in reversed(selected):
            self.path_list.DeleteItem(index)

    def _validate_new_path(self, path):
        normalized = os.path.normcase(os.path.normpath(path))
        for index in range(self.path_list.GetItemCount()):
            existing = os.path.normcase(os.path.normpath(
                self.path_list.GetItemText(index, 1)))
            if normalized == existing:
                wx.MessageBox(_('This path is already in the list.'), APP_NAME,
                              wx.OK | wx.ICON_INFORMATION, self)
                return False
        if not self.delete_paths:
            return True

        from bleachbit import ProtectedPath
        if ProtectedPath.check_protected_path(path) is None:
            return True
        if not self.expert_mode_getter():
            wx.MessageBox(
                _('This path is protected. To bypass protection, enable expert mode.'),
                APP_NAME, wx.OK | wx.ICON_WARNING, self)
            return False
        impact = ProtectedPath.calculate_impact(path)
        warning = ProtectedPath.get_warning_message(path, impact)
        return wx.MessageBox(
            warning, APP_NAME,
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING, self) == wx.YES

    def get_values(self):
        """Return the edited path list in the Options storage format."""
        values = []
        for index in range(self.path_list.GetItemCount()):
            path_type = 'file' if self.path_list.GetItemData(index) == 0 else 'folder'
            values.append((path_type, self.path_list.GetItemText(index, 1)))
        return values


class CookiePanel(wx.Panel):
    """Accessible cookie keep-list editor with asynchronous discovery."""

    def __init__(self, parent):
        super().__init__(parent)
        from bleachbit.Cookie import load_keep_list
        self.all_hosts = set(load_keep_list())
        self.selected_hosts = set(self.all_hosts)
        self._updating = False

        instruction = wx.StaticText(
            self,
            label=_('Select the cookies to keep when cleaning across browsers.'))
        self.search = wx.SearchCtrl(self)
        self.search.SetName(_('Search cookies'))
        self.search.SetDescriptiveText(_('Filter cookies'))
        self.cookie_list = wx.ListCtrl(
            self, style=wx.LC_REPORT | wx.BORDER_SUNKEN)
        self.cookie_list.SetName(_('Cookies to keep'))
        self.cookie_list.InsertColumn(0, _('Host'))
        if not self.cookie_list.EnableCheckBoxes(True):
            raise RuntimeError('This platform does not support accessible list checkboxes')
        self.cookie_list.Bind(wx.EVT_LIST_ITEM_CHECKED, self._on_checked)
        self.cookie_list.Bind(wx.EVT_LIST_ITEM_UNCHECKED, self._on_unchecked)
        self.search.Bind(wx.EVT_TEXT, lambda _event: self._refresh())

        self.status = wx.StaticText(self, label=_('Loading cookies…'))
        select_all = wx.Button(self, label=_('Select &all shown'))
        deselect_all = wx.Button(self, label=_('&Deselect all shown'))
        select_all.Bind(wx.EVT_BUTTON, lambda _event: self._set_shown(True))
        deselect_all.Bind(wx.EVT_BUTTON, lambda _event: self._set_shown(False))
        buttons = wx.BoxSizer(wx.HORIZONTAL)
        buttons.Add(select_all, 0, wx.RIGHT, 8)
        buttons.Add(deselect_all)

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(instruction, 0, wx.ALL, 10)
        sizer.Add(self.search, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        sizer.Add(self.cookie_list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        sizer.Add(self.status, 0, wx.ALL, 10)
        sizer.Add(buttons, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        self.SetSizer(sizer)
        self._refresh()
        threading.Thread(
            target=self._discover, name='CookieDiscovery', daemon=True).start()

    def _discover(self):
        try:
            from bleachbit.Cookie import list_unique_cookies
            discovered = list_unique_cookies()
        except (OSError, RuntimeError, ValueError):
            logger.exception('Failed to enumerate cookies')
            discovered = []
        wx.CallAfter(self._finish_discovery, discovered)

    def _finish_discovery(self, discovered):
        try:
            if self.IsBeingDeleted():
                return
        except RuntimeError:
            return
        self.all_hosts.update(host.strip() for host in discovered if host)
        self._refresh()

    def _shown_hosts(self):
        query = self.search.GetValue().strip().casefold()
        return [host for host in sorted(self.all_hosts, key=str.casefold)
                if not query or query in host.casefold()]

    def _refresh(self):
        hosts = self._shown_hosts()
        self._updating = True
        try:
            self.cookie_list.DeleteAllItems()
            for index, host in enumerate(hosts):
                self.cookie_list.InsertItem(index, host)
                self.cookie_list.CheckItem(index, host in self.selected_hosts)
            self.cookie_list.SetColumnWidth(0, wx.LIST_AUTOSIZE_USEHEADER)
        finally:
            self._updating = False
        self._update_status(len(hosts))

    def _update_status(self, visible=None):
        if visible is None:
            visible = len(self._shown_hosts())
        self.status.SetLabel(
            _('%(selected)d of %(total)d cookies kept; %(visible)d shown') % {
                'selected': len(self.selected_hosts),
                'total': len(self.all_hosts),
                'visible': visible})

    def _host_at(self, index):
        if 0 <= index < self.cookie_list.GetItemCount():
            return self.cookie_list.GetItemText(index)
        return None

    def _on_checked(self, event):
        if not self._updating:
            host = self._host_at(event.GetIndex())
            if host:
                self.selected_hosts.add(host)
                self._update_status()

    def _on_unchecked(self, event):
        if not self._updating:
            host = self._host_at(event.GetIndex())
            if host:
                self.selected_hosts.discard(host)
                self._update_status()

    def _set_shown(self, selected):
        shown = set(self._shown_hosts())
        if selected:
            self.selected_hosts.update(shown)
        else:
            self.selected_hosts.difference_update(shown)
        self._refresh()

    def save(self):
        """Persist selected cookie hosts to the shared keep-list format."""
        from bleachbit.Cookie import COOKIE_KEEP_LIST_FILENAME
        path = os.path.join(bleachbit.options_dir, COOKIE_KEEP_LIST_FILENAME)
        os.makedirs(bleachbit.options_dir, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as cookie_file:
            json.dump(sorted(self.selected_hosts), cookie_file, indent=2)


class PreferencesDialog(wx.Dialog):
    """Native preferences needed for a complete cleaning workflow."""

    _SETTINGS = (
        ('expert_mode', _('&Expert mode (show and allow high-risk options)')),
        ('shred', _('&Overwrite file contents when cleaning')),
        ('delete_confirmation', _('&Confirm before cleaning')),
        ('exit_done', _('E&xit after cleaning finishes')),
    )

    def __init__(self, parent):
        super().__init__(parent, title=_('Preferences'),
                         size=(700, 520),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.SetName(_('Preferences'))
        notebook = wx.Notebook(self)
        general_panel = wx.Panel(notebook)
        sizer = wx.BoxSizer(wx.VERTICAL)
        intro = wx.StaticText(
            general_panel, label=_('Choose cleaning and safety preferences.'))
        sizer.Add(intro, 0, wx.ALL, 12)
        self.controls = {}
        for key, label in self._SETTINGS:
            control = wx.CheckBox(general_panel, label=label)
            control.SetValue(bool(options.get(key)))
            self.controls[key] = control
            sizer.Add(control, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        general_panel.SetSizer(sizer)
        self.custom_panel = PathListPanel(
            notebook, options.get_custom_paths(), _('Custom cleaning paths'),
            delete_paths=True,
            expert_mode_getter=lambda: self.controls['expert_mode'].GetValue())
        self.keep_panel = PathListPanel(
            notebook, options.get_whitelist_paths(), _('Protected paths'))
        self.cookie_panel = CookiePanel(notebook)
        notebook.AddPage(general_panel, _('General'))
        notebook.AddPage(self.custom_panel, _('Custom'))
        notebook.AddPage(self.keep_panel, _('Keep list'))
        notebook.AddPage(self.cookie_panel, _('Cookies'))

        buttons = self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL)
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(notebook, 1, wx.EXPAND | wx.ALL, 8)
        outer.Add(buttons, 0, wx.EXPAND | wx.ALL, 10)
        self.SetSizer(outer)
        self.SetMinSize((620, 440))

    def save(self):
        """Persist the displayed preferences."""
        for key, control in self.controls.items():
            options.set(key, control.GetValue())
        options.set_custom_paths(self.custom_panel.get_values())
        options.set_whitelist_paths(self.keep_panel.get_values())
        try:
            self.cookie_panel.save()
        except OSError as exc:
            logger.exception('Failed to save cookie keep list')
            wx.MessageBox(
                _('The cookie keep list could not be saved: %s') % exc,
                APP_NAME, wx.OK | wx.ICON_ERROR, self)


class SystemInformationDialog(wx.Dialog):
    """Native, keyboard-friendly system information dialog."""

    def __init__(self, parent):
        super().__init__(parent, title=_('System information'),
                         size=(720, 520),
                         style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.SetName(_('System information'))
        from bleachbit.SystemInformation import get_system_information
        self.original_text = get_system_information()
        self.text = wx.TextCtrl(
            self, value=self.original_text,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_DONTWRAP)
        self.text.SetName(_('System information'))
        anonymize_button = wx.Button(self, label=_('&Anonymize'))
        copy_button = wx.Button(self, label=_('&Copy'))
        close_button = wx.Button(self, wx.ID_CLOSE, label=_('&Close'))
        anonymize_button.Bind(wx.EVT_BUTTON, self._on_anonymize)
        copy_button.Bind(wx.EVT_BUTTON, self._on_copy)
        close_button.Bind(wx.EVT_BUTTON, lambda _event: self.EndModal(wx.ID_CLOSE))
        buttons = wx.BoxSizer(wx.HORIZONTAL)
        buttons.AddStretchSpacer()
        buttons.Add(anonymize_button, 0, wx.RIGHT, 8)
        buttons.Add(copy_button, 0, wx.RIGHT, 8)
        buttons.Add(close_button)
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.text, 1, wx.EXPAND | wx.ALL, 10)
        sizer.Add(buttons, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        self.SetSizer(sizer)

    def _on_anonymize(self, event):
        from bleachbit.SystemInformation import anonymize_system_information
        self.text.SetValue(anonymize_system_information(self.original_text))
        event.GetEventObject().Disable()

    def _on_copy(self, _event):
        if wx.TheClipboard.Open():
            try:
                wx.TheClipboard.SetData(wx.TextDataObject(self.text.GetValue()))
                wx.TheClipboard.Flush()
            finally:
                wx.TheClipboard.Close()


class MainFrame(wx.Frame):
    """Main window composed of native, NVDA-readable controls."""

    def __init__(self, app, auto_exit=False, shred_paths=None):
        super().__init__(None, title=APP_NAME, size=(1000, 700))
        self.SetName(APP_NAME)
        if bleachbit.appicon_path and os.path.exists(bleachbit.appicon_path):
            icon = wx.Icon(bleachbit.appicon_path, wx.BITMAP_TYPE_ANY)
            if icon.IsOk():
                self.SetIcon(icon)
        self.app = app
        self.auto_exit = bool(auto_exit)
        self.shred_paths_on_start = list(shred_paths or ())
        self.rows = []
        self.worker = None
        self.worker_thread = None
        self.start_time = None
        self._updating_checks = False
        self._destroyed = False
        self._close_when_done = False
        self._showed_startup_messages = False
        self._checked_orphaned_wipe_files = False
        self._log_handler = _WxLogHandler(self)
        logging.getLogger('bleachbit').addHandler(self._log_handler)

        self._build_menu()
        self._build_controls()
        self.Bind(wx.EVT_CLOSE, self._on_close)
        self.Centre()
        self.Show()

        if self.auto_exit and not self.shred_paths_on_start:
            wx.CallAfter(self._finish_auto_exit)
        else:
            self._load_cleaners()

    def _build_menu(self):
        menu_bar = wx.MenuBar()
        file_menu = wx.Menu()
        shred_files_item = file_menu.Append(
            wx.ID_ANY, _('Shred &files…\tCtrl+Shift+F'))
        shred_folder_item = file_menu.Append(
            wx.ID_ANY, _('Shred f&older…\tCtrl+Shift+O'))
        shred_clipboard_item = file_menu.Append(
            wx.ID_ANY, _('Shred paths from &clipboard'))
        wipe_space_item = file_menu.Append(
            wx.ID_ANY, _('Wipe &empty space…'))
        file_menu.AppendSeparator()
        preferences_item = file_menu.Append(wx.ID_PREFERENCES, _('&Preferences\tCtrl+,'))
        file_menu.AppendSeparator()
        exit_item = file_menu.Append(wx.ID_EXIT, _('E&xit\tCtrl+Q'))
        help_menu = wx.Menu()
        help_item = help_menu.Append(wx.ID_HELP, _('&Help contents\tF1'))
        system_item = help_menu.Append(wx.ID_ANY, _('&System information'))
        about_item = help_menu.Append(wx.ID_ABOUT, _('&About'))
        menu_bar.Append(file_menu, _('&File'))
        menu_bar.Append(help_menu, _('&Help'))
        self.SetMenuBar(menu_bar)
        self._operation_menu_ids = (
            shred_files_item.GetId(), shred_folder_item.GetId(),
            shred_clipboard_item.GetId(), wipe_space_item.GetId())
        self.Bind(wx.EVT_MENU, self._on_shred_files, shred_files_item)
        self.Bind(wx.EVT_MENU, self._on_shred_folder, shred_folder_item)
        self.Bind(wx.EVT_MENU, self._on_shred_clipboard, shred_clipboard_item)
        self.Bind(wx.EVT_MENU, self._on_wipe_empty_space, wipe_space_item)
        self.Bind(wx.EVT_MENU, self._on_preferences, preferences_item)
        self.Bind(wx.EVT_MENU, lambda _event: self.Close(), exit_item)
        self.Bind(wx.EVT_MENU, self._on_help, help_item)
        self.Bind(wx.EVT_MENU, self._on_system_information, system_item)
        self.Bind(wx.EVT_MENU, self._on_about, about_item)

    def _build_controls(self):
        panel = wx.Panel(self)
        outer = wx.BoxSizer(wx.VERTICAL)

        instructions = wx.StaticText(
            panel,
            label=_('Select cleaner options, then choose Preview or Clean.'))
        outer.Add(instructions, 0, wx.ALL, 10)

        self.option_list = wx.ListCtrl(
            panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.BORDER_SUNKEN)
        self.option_list.SetName(_('Cleaner options'))
        self.option_list.SetHelpText(
            _('A checklist of cleaner options. Use Space to change the checked state.'))
        self.option_list.InsertColumn(0, _('Cleaner'))
        self.option_list.InsertColumn(1, _('Option'))
        self.option_list.InsertColumn(2, _('Description'))
        self.option_list.InsertColumn(3, _('Space'))
        if not hasattr(self.option_list, 'EnableCheckBoxes'):
            raise RuntimeError('wxPython 4.2 or newer is required for accessible checkboxes')
        if not self.option_list.EnableCheckBoxes(True):
            raise RuntimeError('This platform does not support accessible list checkboxes')
        if hasattr(wx, 'EVT_LIST_ITEM_CHECKED'):
            self.option_list.Bind(wx.EVT_LIST_ITEM_CHECKED, self._on_item_checked)
            self.option_list.Bind(wx.EVT_LIST_ITEM_UNCHECKED, self._on_item_unchecked)
        self.option_list.Bind(wx.EVT_CHAR_HOOK, self._on_list_key)
        outer.Add(self.option_list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        button_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.preview_button = wx.Button(panel, label=_('&Preview'))
        self.clean_button = wx.Button(panel, label=_('&Clean'))
        self.abort_button = wx.Button(panel, label='&' + ABORT_BUTTON_LABEL)
        self.preview_button.SetName(_('Preview'))
        self.clean_button.SetName(_('Clean'))
        self.abort_button.SetName(ABORT_BUTTON_LABEL)
        self.abort_button.Disable()
        self.preview_button.Bind(wx.EVT_BUTTON, lambda _event: self._start_operation(False))
        self.clean_button.Bind(wx.EVT_BUTTON, lambda _event: self._start_operation(True))
        self.abort_button.Bind(wx.EVT_BUTTON, self._on_abort)
        button_sizer.Add(self.preview_button, 0, wx.RIGHT, 8)
        button_sizer.Add(self.clean_button, 0, wx.RIGHT, 8)
        button_sizer.Add(self.abort_button)
        outer.Add(button_sizer, 0, wx.ALL, 10)

        self.progress_text = wx.StaticText(panel, label=_('Loading cleaners…'))
        self.progress_text.SetName(_('Operation status'))
        outer.Add(self.progress_text, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        self.progress = wx.Gauge(panel, range=100)
        self.progress.SetName(_('Operation progress'))
        outer.Add(self.progress, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        activity_label = wx.StaticText(panel, label=_('&Activity log'))
        outer.Add(activity_label, 0, wx.LEFT | wx.RIGHT, 10)
        self.output = wx.TextCtrl(
            panel, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2)
        self.output.SetName(_('Activity log'))
        outer.Add(self.output, 1, wx.EXPAND | wx.ALL, 10)

        panel.SetSizer(outer)
        self.status_bar = self.CreateStatusBar()
        self.status_bar.SetName(_('Status'))
        self.status_bar.SetStatusText(_('Starting…'))

    def _load_cleaners(self):
        self._set_busy(True)

        def load():
            try:
                for _result in register_cleaners(self.update_progress_bar):
                    pass
                rows = cleaner_options(backends)
            except Exception as exc:  # keep the native event loop alive
                logger.exception('Error loading cleaners')
                wx.CallAfter(self._loading_failed, str(exc))
            else:
                wx.CallAfter(self._cleaners_loaded, rows)

        threading.Thread(target=load, name='CleanerLoader', daemon=True).start()

    def _cleaners_loaded(self, rows):
        if self._destroyed:
            return
        self.rows = rows
        self._updating_checks = True
        try:
            self.option_list.DeleteAllItems()
            for index, row in enumerate(rows):
                item = self.option_list.InsertItem(index, row.cleaner_name)
                self.option_list.SetItem(item, 1, row.option_name)
                self.option_list.SetItem(item, 2, row.description)
                self.option_list.SetItemData(item, index)
                selected = bool(options.get_tree(
                    row.cleaner_id, row.option_id))
                if selected and row.warning and not options.get('expert_mode'):
                    # Do not expose a stale high-risk selection after expert
                    # mode has been disabled in another session.
                    selected = False
                    options.set_tree(row.cleaner_id, row.option_id, False)
                self.option_list.CheckItem(
                    item, selected)
            for column in range(4):
                self.option_list.SetColumnWidth(column, wx.LIST_AUTOSIZE_USEHEADER)
            if rows:
                self.option_list.SetColumnWidth(2, max(320, self.option_list.GetColumnWidth(2)))
        finally:
            self._updating_checks = False
        self._set_busy(False)
        self._announce(_('Cleaners loaded. %d options available.') % len(rows))
        if rows:
            self.option_list.SetFocus()
        if self.shred_paths_on_start:
            wx.CallAfter(self._start_shred_paths)
        else:
            self._show_startup_messages()
            self._check_orphaned_wipe_files()

    def _show_startup_messages(self):
        if self._showed_startup_messages:
            return
        self._showed_startup_messages = True
        try:
            from bleachbit.GuiStartup import get_startup_messages
            messages = get_startup_messages(auto_exit=False)
        except Exception:
            logger.exception('Failed to collect startup messages')
            return
        for message, is_error in messages:
            self.append_text(message + '\n', 'error' if is_error else None)

    def _check_orphaned_wipe_files(self):
        if self._checked_orphaned_wipe_files:
            return
        self._checked_orphaned_wipe_files = True
        from bleachbit.Wipe import detect_orphaned_wipe_files
        orphaned_files = detect_orphaned_wipe_files()
        if not orphaned_files:
            return
        answer = wx.MessageBox(
            _('BleachBit detected leftover files from an interrupted disk '
              'wipe operation. Permanently remove them now?'),
            APP_NAME, wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING, self)
        if answer == wx.YES:
            self._confirm_and_shred(orphaned_files, already_confirmed=True)

    def _loading_failed(self, detail):
        if self._destroyed:
            return
        self._set_busy(False)
        self._announce(_('Cleaners could not be loaded.'))
        wx.MessageBox(_('Cleaners could not be loaded: %s') % detail,
                      APP_NAME, wx.OK | wx.ICON_ERROR, self)

    def _on_item_checked(self, event):
        if self._updating_checks:
            return
        index = event.GetIndex()
        if index < 0 or index >= len(self.rows):
            return
        row = self.rows[index]
        if row.warning:
            if not options.get('expert_mode'):
                self._updating_checks = True
                try:
                    self.option_list.CheckItem(index, False)
                finally:
                    self._updating_checks = False
                wx.MessageBox(REQUIRES_EXPERT_MODE + '\n\n' + row.warning,
                              APP_NAME, wx.OK | wx.ICON_WARNING, self)
                return
            answer = wx.MessageBox(row.warning + '\n\n' + _('Enable this option?'),
                                   APP_NAME,
                                   wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING,
                                   self)
            if answer != wx.YES:
                self._updating_checks = True
                try:
                    self.option_list.CheckItem(index, False)
                finally:
                    self._updating_checks = False
                return
        options.set_tree(row.cleaner_id, row.option_id, True)
        self._announce(row.accessible_label + '. ' + _('Checked'))

    def _on_item_unchecked(self, event):
        if self._updating_checks:
            return
        index = event.GetIndex()
        if 0 <= index < len(self.rows):
            row = self.rows[index]
            options.set_tree(row.cleaner_id, row.option_id, False)
            self._announce(row.accessible_label + '. ' + _('Not checked'))

    def _on_list_key(self, event):
        if event.GetKeyCode() == wx.WXK_SPACE:
            index = self.option_list.GetFirstSelected()
            if index != -1:
                self.option_list.CheckItem(
                    index, not self.option_list.IsItemChecked(index))
                return
        event.Skip()

    def _checked_indices(self):
        return [index for index in range(len(self.rows))
                if self.option_list.IsItemChecked(index)]

    def _start_operation(self, really_delete, operations=None,
                         confirm_delete=True):
        if self.worker is not None:
            return
        if operations is None:
            operations = build_operations(
                self.rows, self._checked_indices(),
                bool(options.get('expert_mode')))
        if not operations:
            wx.MessageBox(_('You must select an operation'), APP_NAME,
                          wx.OK | wx.ICON_INFORMATION, self)
            self.option_list.SetFocus()
            return
        if really_delete and confirm_delete and options.get('delete_confirmation'):
            answer = wx.MessageBox(
                _('Permanently delete the files selected for cleaning?'),
                APP_NAME, wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING, self)
            if answer != wx.YES:
                return

        from bleachbit import Worker
        self.output.Clear()
        try:
            self.worker = Worker.Worker(self, really_delete, operations)
        except Exception as exc:
            backends.pop('_gui', None)
            logger.exception('Could not start cleaning operation')
            wx.MessageBox(
                _('The operation could not be started: %s') % exc,
                APP_NAME, wx.OK | wx.ICON_ERROR, self)
            return
        self.start_time = time.time()
        self._set_busy(True, allow_abort=True)
        self._announce(_('Cleaning started.') if really_delete else _('Preview started.'))
        self.worker_thread = threading.Thread(
            target=self._consume_worker,
            args=(self.worker,), name='BleachBitWorker', daemon=True)
        self.worker_thread.start()

    def _consume_worker(self, worker):
        try:
            for keep_going in worker.run():
                if not keep_going:
                    break
        except Exception as exc:  # surface unexpected engine errors to the user
            logger.exception('Cleaning operation failed')
            wx.CallAfter(self._worker_failed, worker, str(exc))

    def _worker_failed(self, worker, detail):
        if self._destroyed or worker is not self.worker:
            return
        self.append_text(_('Operation failed: %s\n') % detail, 'error')
        backends.pop('_gui', None)
        self.worker = None
        self._close_when_done = False
        self._set_busy(False)
        self._announce(_('Operation failed.'))

    def _start_shred_paths(self):
        paths = [path for path in self.shred_paths_on_start
                 if os.path.lexists(path)]
        missing = len(self.shred_paths_on_start) - len(paths)
        if missing:
            self.append_text(_('%d selected path(s) no longer exist.\n') % missing,
                             'error')
        if not paths:
            if self.auto_exit:
                self.Close()
            return
        self._close_when_done = self.auto_exit
        if not self._confirm_and_shred(paths):
            self._close_when_done = False
            if self.auto_exit:
                self.Close()

    def append_text(self, text, _tag=None):
        if self._destroyed:
            return
        wx.CallAfter(self._append_text_ui, str(text))

    def _append_text_ui(self, text):
        if not self._destroyed:
            self.output.AppendText(text)

    def update_progress_bar(self, status):
        wx.CallAfter(self._update_progress_ui, status)

    def _update_progress_ui(self, status):
        if self._destroyed:
            return
        if isinstance(status, float):
            self.progress.SetValue(max(0, min(100, round(status * 100))))
        elif isinstance(status, str):
            self.progress_text.SetLabel(status)
            self.status_bar.SetStatusText(status)
        else:
            raise RuntimeError('unexpected progress type: %s' % type(status))

    def update_item_size(self, cleaner_id, option_id, bytes_removed):
        wx.CallAfter(self._update_item_size_ui,
                     cleaner_id, option_id, bytes_removed)

    def _update_item_size_ui(self, cleaner_id, option_id, bytes_removed):
        if self._destroyed or option_id == -1:
            return
        text = FileUtilities.bytes_to_human(bytes_removed) if bytes_removed else ''
        for index, row in enumerate(self.rows):
            if row.cleaner_id == cleaner_id and row.option_id == option_id:
                self.option_list.SetItem(index, 3, text)
                return

    def update_total_size(self, bytes_removed):
        text = FileUtilities.bytes_to_human(bytes_removed) if bytes_removed else ''
        wx.CallAfter(self.status_bar.SetStatusText, text)

    def worker_done(self, worker, really_delete):
        wx.CallAfter(self._worker_done_ui, worker, really_delete)

    def _worker_done_ui(self, worker, really_delete):
        if self._destroyed or worker is not self.worker:
            return
        backends.pop('_gui', None)
        self.worker = None
        self.progress.SetValue(100)
        self._set_busy(False)
        self._announce(_('Done.'))
        if self._close_when_done or (really_delete and options.get('exit_done')):
            self._close_when_done = False
            self.Close()

    def _set_busy(self, busy, allow_abort=False):
        self.option_list.Enable(not busy)
        self.preview_button.Enable(not busy)
        self.clean_button.Enable(not busy)
        self.abort_button.Enable(busy and allow_abort)
        menu_bar = self.GetMenuBar()
        if menu_bar:
            menu_bar.Enable(wx.ID_PREFERENCES, not busy)
            for menu_id in self._operation_menu_ids:
                menu_bar.Enable(menu_id, not busy)
        if not busy:
            self.abort_button.Disable()

    def _on_abort(self, _event):
        if self.worker is not None:
            self.worker.abort()
            self.abort_button.Disable()
            self._announce(_('Stopping. Please wait.'))

    def _announce(self, message):
        if self._destroyed:
            return
        self.progress_text.SetLabel(message)
        self.status_bar.SetStatusText(message)
        try:
            wx.Accessible.NotifyEvent(
                wx.ACC_EVENT_OBJECT_VALUECHANGE,
                self.progress_text, wx.OBJID_CLIENT, 0)
        except Exception:  # accessibility support varies by Windows version
            logger.debug('Accessibility notification was not available',
                         exc_info=True)

    def _on_preferences(self, _event):
        old_expert_mode = options.get('expert_mode')
        dialog = PreferencesDialog(self)
        try:
            if dialog.ShowModal() == wx.ID_OK:
                dialog.save()
                if old_expert_mode != options.get('expert_mode'):
                    # Rebuild selection state so disabling expert mode also
                    # clears any previously selected high-risk operations.
                    self._cleaners_loaded(self.rows)
        finally:
            dialog.Destroy()

    def _on_shred_files(self, _event):
        dialog = wx.FileDialog(
            self, message=_('Choose files to shred'),
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST | wx.FD_MULTIPLE)
        try:
            if dialog.ShowModal() == wx.ID_OK:
                self._confirm_and_shred(dialog.GetPaths())
        finally:
            dialog.Destroy()

    def _on_shred_folder(self, _event):
        dialog = wx.DirDialog(
            self, message=_('Choose folder to shred'),
            style=wx.DD_DIR_MUST_EXIST)
        try:
            if dialog.ShowModal() == wx.ID_OK:
                self._confirm_and_shred([dialog.GetPath()])
        finally:
            dialog.Destroy()

    def _on_shred_clipboard(self, _event):
        if os.name != 'nt':
            return
        from bleachbit import Windows
        paths = list(Windows.get_clipboard_paths())
        if not paths:
            wx.MessageBox(_('No paths found in clipboard.'), APP_NAME,
                          wx.OK | wx.ICON_INFORMATION, self)
            return
        if self._confirm_and_shred(paths):
            Windows.clear_clipboard()

    def _confirm_and_shred(self, paths, already_confirmed=False):
        existing_paths = [path for path in paths if os.path.lexists(path)]
        if not existing_paths:
            wx.MessageBox(_('No selected paths exist.'), APP_NAME,
                          wx.OK | wx.ICON_INFORMATION, self)
            return False
        if not already_confirmed:
            answer = wx.MessageBox(
                _('Permanently shred %d selected path(s)?') % len(existing_paths),
                APP_NAME, wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING, self)
            if answer != wx.YES:
                return False
        backends['_gui'] = create_simple_cleaner(existing_paths)
        self._start_operation(
            True, {'_gui': ['files']}, confirm_delete=False)
        return True

    def _on_wipe_empty_space(self, _event):
        dialog = wx.DirDialog(
            self, message=_('Choose a folder'), style=wx.DD_DIR_MUST_EXIST)
        try:
            if dialog.ShowModal() != wx.ID_OK:
                return
            path = dialog.GetPath()
        finally:
            dialog.Destroy()
        answer = wx.MessageBox(
            EMPTY_SPACE_WARNING + '\n\n' + _('Continue?'), APP_NAME,
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING, self)
        if answer != wx.YES:
            return
        from bleachbit.Cleaner import create_wipe_empty_space_cleaner
        backends['_gui'] = create_wipe_empty_space_cleaner(path)
        self._start_operation(
            True, {'_gui': ['empty_space']}, confirm_delete=False)

    def _on_help(self, _event):
        import webbrowser
        webbrowser.open(bleachbit.help_contents_url)

    def _on_system_information(self, _event):
        dialog = SystemInformationDialog(self)
        try:
            dialog.ShowModal()
        finally:
            dialog.Destroy()

    def _on_about(self, _event):
        wx.MessageBox(
            '%s %s\n\n%s\n%s' % (
                APP_NAME, APP_VERSION,
                _('Program to clean unnecessary files'), bleachbit.APP_URL),
            _('About %s') % APP_NAME, wx.OK | wx.ICON_INFORMATION, self)

    def _finish_auto_exit(self):
        print('Success')
        self.Close()

    def _on_close(self, event):
        if self.worker is not None:
            answer = wx.MessageBox(
                _('An operation is running. Stop it and close when it is safe?'),
                APP_NAME, wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING, self)
            if answer == wx.YES:
                self._close_when_done = True
                self.worker.abort()
                self.abort_button.Disable()
                self._announce(_('Stopping. Please wait.'))
            event.Veto()
            return
        self._destroyed = True
        logging.getLogger('bleachbit').removeHandler(self._log_handler)
        event.Skip()


class Bleachbit:
    """Application facade matching the existing GTK application's API."""

    def __init__(self, uac=True, shred_paths=None, auto_exit=False):
        self.shred_paths = list(shred_paths or ())
        self.auto_exit = bool(auto_exit)
        if os.name == 'nt':
            import atexit
            from bleachbit import Windows
            if Windows.elevate_privileges(uac):
                sys.exit(0)
            # Match the legacy application's cleanup of UAC handshake files.
            atexit.register(Windows.cleanup_nonce)

    def run(self, _argv=None):
        """Run the wx event loop and return a process exit status."""
        app = wx.App(False)
        app.SetAppName(APP_NAME)
        MainFrame(app, auto_exit=self.auto_exit,
                  shred_paths=self.shred_paths)
        result = app.MainLoop()
        return result if isinstance(result, int) else 0

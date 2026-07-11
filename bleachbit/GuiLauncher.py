# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2008-2026 Andrew Ziem.
#
# This work is licensed under the terms of the GNU GPL, version 3 or
# later.  See the COPYING file in the top-level directory.

"""Choose the native accessible GUI on Windows and GTK elsewhere."""

import importlib.util
import os


def _module_available(module_name):
    """Return whether a top-level module can be imported."""
    try:
        return importlib.util.find_spec(module_name) is not None
    except (ImportError, ValueError):
        return False


def select_gui_toolkit(platform_name=None, environ=None):
    """Return ``wx`` or ``gtk`` for the current environment.

    ``BLEACHBIT_GUI_TOOLKIT`` is primarily a migration and troubleshooting
    escape hatch.  The accessible wx frontend is the Windows default.
    """
    platform_name = os.name if platform_name is None else platform_name
    environ = os.environ if environ is None else environ
    override = environ.get('BLEACHBIT_GUI_TOOLKIT', '').strip().lower()
    if override in ('wx', 'gtk'):
        return override
    return 'wx' if platform_name == 'nt' else 'gtk'


def is_gui_available(platform_name=None, environ=None):
    """Return whether the selected GUI toolkit is installed and usable."""
    toolkit = select_gui_toolkit(platform_name, environ)
    if toolkit == 'wx':
        return _module_available('wx')
    from bleachbit.GtkShim import HAVE_GTK
    return HAVE_GTK


def run_gui(uac=True, shred_paths=None, auto_exit=False, argv=None):
    """Create and run the selected graphical application."""
    if select_gui_toolkit() == 'wx':
        from bleachbit.WxApplication import Bleachbit
    else:
        from bleachbit.GuiApplication import Bleachbit
    app = Bleachbit(uac=uac, shred_paths=shred_paths,
                   auto_exit=auto_exit)
    if argv is None:
        return app.run()
    return app.run(argv)


# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 Andrew Ziem
#
# This work is licensed under the terms of the GNU GPL, version 3 or
# later.  See the COPYING file in the top-level directory.

"""Helpers for exposing GTK widgets to assistive technologies.

GTK 3 exposes widgets through ATK, but application-specific names,
label relationships, and transient status messages must still be supplied by
the application.  Keep that plumbing here so dialogs use it consistently.
"""

from bleachbit.GtkShim import GObject


def _get_accessible(widget):
    """Return *widget*'s accessible object, or ``None`` when unavailable."""
    if widget is None or not hasattr(widget, 'get_accessible'):
        return None
    return widget.get_accessible()


def set_accessible_name(widget, name, description=None):
    """Set a stable screen-reader name and optional description on *widget*."""
    accessible = _get_accessible(widget)
    if accessible is None:
        return
    accessible.set_name(name)
    if description:
        accessible.set_description(description)


def label_control(label, control, name=None, description=None):
    """Associate a visible ``Gtk.Label`` with the control it describes.

    ``set_mnemonic_widget`` establishes GTK's labelled-by accessibility
    relation.  An explicit name is also set because not every platform bridge
    derives a useful name from that relation.
    """
    label.set_mnemonic_widget(control)
    if name is None:
        name = label.get_text().strip().rstrip(':').strip()
    set_accessible_name(control, name, description)


def _supports_signal(accessible, signal_name):
    """Return whether the accessible object's runtime supports *signal_name*."""
    if GObject is None or accessible is None:
        return False
    gtype = getattr(accessible, '__gtype__', None)
    return bool(gtype and GObject.signal_lookup(signal_name, gtype))


def announce(widget, message, assertive=False):
    """Expose and announce a transient status message without moving focus.

    ATK 2.50 added ``notification`` and ATK 2.46 added ``announcement``.
    Older GTK distributions still receive the accessible-name change, so this
    remains useful and safe across the GTK versions supported by BleachBit.
    """
    if not message:
        return
    accessible = _get_accessible(widget)
    if accessible is None:
        return

    accessible.set_name(message)
    if _supports_signal(accessible, 'notification'):
        # AtkLive has values POLITE=0 and ASSERTIVE=1.
        try:
            accessible.emit('notification', message, 1 if assertive else 0)
            return
        except (TypeError, ValueError, RuntimeError):
            # Some downstream GTK bundles expose a newer signal through
            # introspection while linking an older bridge.  Fall through to
            # the older signal instead of breaking the user action.
            pass
    if _supports_signal(accessible, 'announcement'):
        try:
            accessible.emit('announcement', message)
        except (TypeError, ValueError, RuntimeError):
            # The accessible-name update above is the compatibility fallback.
            pass

# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2008-2026 Andrew Ziem.
#
# This work is licensed under the terms of the GNU GPL, version 3 or
# later.  See the COPYING file in the top-level directory.

"""Toolkit-independent support for the accessible wxPython interface."""

from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Sequence


@dataclass(frozen=True)
class CleanerOption:
    """One selectable cleaner option shown by the wx frontend."""

    cleaner_id: str
    option_id: str
    cleaner_name: str
    option_name: str
    description: str
    warning: str = ''

    @property
    def accessible_label(self):
        """Return a useful standalone label for a screen reader."""
        parts = [self.cleaner_name, self.option_name]
        if self.description:
            parts.append(self.description)
        if self.warning:
            parts.append(self.warning)
        return '. '.join(part.strip().rstrip('.') for part in parts if part)


def cleaner_options(backends: Mapping[str, object]) -> List[CleanerOption]:
    """Flatten usable cleaner backends into deterministic option rows."""
    rows = []
    for cleaner_id in sorted(backends,
                             key=lambda key: backends[key].get_name().casefold()):
        backend = backends[cleaner_id]
        # The built-in System cleaner implements get_commands() directly and
        # therefore has no ActionProvider entries for is_usable() to count.
        if cleaner_id == '_gui' or (
                cleaner_id != 'system' and not backend.is_usable()):
            continue
        descriptions = getattr(backend, 'options', {})
        for option_id, option_name in backend.get_options():
            option_data = descriptions.get(option_id, ())
            description = option_data[1] if len(option_data) > 1 else ''
            rows.append(CleanerOption(
                cleaner_id=cleaner_id,
                option_id=option_id,
                cleaner_name=backend.get_name(),
                option_name=option_name,
                description=description or '',
                warning=backend.get_warning(option_id) or ''))
    return rows


def build_operations(rows: Sequence[CleanerOption],
                     checked_indices: Iterable[int],
                     expert_mode: bool) -> Dict[str, List[str]]:
    """Build Worker operations, enforcing expert-mode guardrails."""
    operations = {}  # type: Dict[str, List[str]]
    for index in sorted(set(checked_indices)):
        if index < 0 or index >= len(rows):
            continue
        row = rows[index]
        if row.warning and not expert_mode:
            continue
        operations.setdefault(row.cleaner_id, []).append(row.option_id)
    return operations

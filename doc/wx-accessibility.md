# Accessible Windows interface

On Microsoft Windows, BleachBit uses a wxPython interface by default. Its
checklist, buttons, dialogs, status text, and activity log are native Windows
controls, so screen readers such as NVDA can identify their names, roles,
checked states, and values.

Keyboard workflow:

1. Move through cleaner options with the arrow keys.
2. Press Space to check or uncheck the focused option.
3. Press Alt+P to preview or Alt+C to clean.
4. Press Alt+A to abort a running operation safely.

High-risk options remain blocked until Expert mode is enabled in Preferences.
The application asks for confirmation both when enabling a high-risk option and
before permanently cleaning files.

The File menu provides native dialogs for shredding files, folders, and paths
copied to the clipboard, plus wiping empty space. Preferences uses native tab,
list, checkbox, and file-picker controls for general safety settings, custom
cleaning paths, protected paths, and the cookie keep list. Protected custom
paths retain the same expert-mode guardrails as the legacy interface.

For migration troubleshooting only, set `BLEACHBIT_GUI_TOOLKIT=gtk` before
starting BleachBit to use the legacy GTK interface. GTK remains the default on
non-Windows platforms.

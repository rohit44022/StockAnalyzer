"""Isolated quick-notes module — persists user-scoped scratchpad notes
in the shared SQLite DB. Cleared on logout. Survives browser refresh.

This module does NOT touch any other module. It is consumed only by
web/notes_routes.py and the floating widget partial _notepad_widget.html.
"""

"""Itinerary export — PDF / XLSX downloads with per-day notes.

Pure derivation over the graph (``grouping``), day-notes generation with an
LLM + deterministic fallback (``day_notes``), and the two renderers
(``pdf``, ``xlsx``). The export never reads Dossier / OSINT / profile
tiers — everything it emits is traveler-safe by construction.
"""

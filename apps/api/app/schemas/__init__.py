"""Pydantic request/response schemas decoupled from SQLAlchemy models.

S03 is the first slice large enough to justify separating HTTP payload
shapes from ORM models — client creation ships a deeply-nested Voodoo
Doll payload that has no business leaking into ``app.models``.
"""

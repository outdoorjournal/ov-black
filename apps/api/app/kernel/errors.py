"""Kernel structural violations.

A ``KernelViolation`` means the requested operation would break a structural
invariant — it is the kernel refusing to *represent* an illegal state, not a
feasibility judgement. Feasibility problems (an overlapping dinner, a flight
that lands too late) are never exceptions; they come back as findings from
``app.kernel.analysis`` so callers can hold an infeasible graph while fixing it.
"""

from __future__ import annotations


class KernelViolation(Exception):
    """A structural invariant would be broken; the operation does not exist."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

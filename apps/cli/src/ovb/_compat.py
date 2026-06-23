"""Small shims over the machine-generated models.

datamodel-code-generator wraps some constrained scalars (e.g. ``cost_amount``)
in a pydantic ``RootModel`` rather than inlining them. ``unwrap_root`` peels
that wrapper so invariant math and rendering see the primitive value.
"""

from __future__ import annotations

from typing import Any

from pydantic import RootModel


def unwrap_root(value: Any) -> Any:
    """Return the inner value of a RootModel scalar, else ``value`` unchanged."""
    return value.root if isinstance(value, RootModel) else value

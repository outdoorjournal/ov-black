"""CloudWatch EMF metrics (M005 / obs).

We emit metrics as `Embedded Metric Format <https://docs.aws.amazon.com/
AmazonCloudWatch/latest/monitoring/CloudWatch_Embedded_Metric_Format.html>`_
log lines: CloudWatch auto-extracts a metric from any log record carrying an
``_aws`` block, so there is **zero** extra infra (no PutMetricData calls, no
agent) — the ECS awslogs driver already ships these lines to CloudWatch Logs.

Locally the same line is just JSON on stdout (or muted via ``METRICS_ENABLED=
false``). ``Env`` + ``Service`` dimensions are added automatically; the bound
``request_id`` rides along as a queryable (non-dimension) field.

This is the lightweight seam the OTel-ready design swaps later: replace
:func:`emit_metric` (or point it at an OTel meter) without touching call sites.
"""

from __future__ import annotations

import json
import logging
import time
from typing import TYPE_CHECKING, Any

from app.config import get_settings
from app.observability.context import get_request_id

if TYPE_CHECKING:
    from collections.abc import Mapping

_logger = logging.getLogger("ov_black.metrics")


def emit_metric(
    name: str,
    value: float,
    *,
    unit: str = "Count",
    dimensions: Mapping[str, Any] | None = None,
    **fields: Any,
) -> None:
    """Emit one EMF metric line.

    ``dimensions`` become a CloudWatch dimension set (string values, low
    cardinality only — never raw ids/paths). ``fields`` are extra context logged
    alongside but NOT used as dimensions. Failures are swallowed: telemetry must
    never break a request.
    """
    settings = get_settings()
    if not settings.metrics_enabled:
        return

    try:
        dims: dict[str, str] = {k: str(v) for k, v in (dimensions or {}).items() if v is not None}
        dims.setdefault("Service", settings.service_name)
        dims.setdefault("Env", settings.env)

        body: dict[str, Any] = {
            "_aws": {
                "Timestamp": int(time.time() * 1000),
                "CloudWatchMetrics": [
                    {
                        "Namespace": settings.metrics_namespace,
                        "Dimensions": [sorted(dims.keys())],
                        "Metrics": [{"Name": name, "Unit": unit}],
                    }
                ],
            },
            name: float(value),
            **dims,
        }
        rid = get_request_id()
        if rid:
            body["request_id"] = rid
        for key, val in fields.items():
            if val is not None and key not in body:
                body[key] = val

        _logger.info(json.dumps(body, default=str))
    except Exception:  # noqa: BLE001 — telemetry is best-effort, never fatal
        _logger.debug("metrics.emit_failed", exc_info=True)

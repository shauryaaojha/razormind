"""The registered tool set. Registration happens once, at import.

Kept apart from ``registry.py`` so that the registry class can be imported and
instantiated -- by a test, by a future multi-tenant registry -- without pulling
in every tool and every table they read. Importing this module is what makes a
tool resolvable, and it is the only place a new tool is wired in.
"""

from .finance.reconciliation import ReconciliationTool
from .finance.refunds import RefundAnalysisTool
from .finance.revenue import RevenueAnalysisTool
from .payments.failure import FailureAnalysisTool
from .registry import ToolRegistry
from .risk.chargebacks import ChargebackAnalysisTool

__all__ = ["REGISTRY", "build_registry"]


def build_registry() -> ToolRegistry:
    """A registry holding every v1 tool."""
    registry = ToolRegistry()
    registry.register(ReconciliationTool())
    registry.register(RevenueAnalysisTool())
    registry.register(FailureAnalysisTool())
    registry.register(RefundAnalysisTool())
    registry.register(ChargebackAnalysisTool())
    return registry


#: The process-wide registry. Phase 6's planner and validator resolve against it.
REGISTRY = build_registry()

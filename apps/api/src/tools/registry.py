"""Register, resolve, describe (docs/04-tool-contract.md#registry).

The registry is the extension point: a new tool is a registration plus a
golden test, and no change to the planner, executor, verifier or UI. If adding
one forces a change to any of those, the contract has been violated somewhere.

Resolution is by ``name`` and optionally ``version``. With no version the
highest registered version wins, so a plan that pins nothing gets the current
formula while an old execution's evidence keeps naming the version that
actually produced it.
"""

from typing import Any

from .base import DeterministicTool, ToolError, ToolSpec

__all__ = ["AnyTool", "ToolRegistry", "parse_version"]

#: The registry is heterogeneous by nature -- every tool has its own input and
#: output models -- so it stores them without pinning those parameters. The
#: types are recovered at the call site, where the concrete tool is known.
type AnyTool = DeterministicTool[Any, Any]


def parse_version(version: str) -> tuple[int, int]:
    """``"1.0"`` -> ``(1, 0)``. MAJOR bumps on a formula change, MINOR on a field.

    Parsed rather than compared as a string because ``"10.0" < "9.0"``
    lexicographically, and the day that matters is the day a tool reaches its
    tenth revision and silently resolves to an older formula.
    """
    parts = version.split(".")
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        raise ToolError(
            "INVALID_TOOL_VERSION",
            f"version {version!r} is not MAJOR.MINOR",
            {"version": version},
        )
    return int(parts[0]), int(parts[1])


class ToolRegistry:
    """The set of tools this process can run."""

    def __init__(self) -> None:
        self._tools: dict[tuple[str, str], AnyTool] = {}

    def register(self, tool: AnyTool) -> None:
        """Add a tool. Registration happens once, at import.

        The ``ClassVar`` checks look pedantic until a tool declares no ``name``:
        the failure then surfaces as an ``AttributeError`` from somewhere deep
        in the executor rather than here, where it names the class.
        """
        for attribute in ("name", "version", "input_model", "output_model"):
            if getattr(type(tool), attribute, None) is None:
                raise ToolError(
                    "INVALID_TOOL",
                    f"{type(tool).__name__} declares no {attribute}",
                    {"tool": type(tool).__name__, "missing": attribute},
                )
        parse_version(tool.version)
        key = (tool.name, tool.version)
        if key in self._tools:
            raise ToolError(
                "DUPLICATE_TOOL",
                f"{tool.name} v{tool.version} is already registered",
                {"name": tool.name, "version": tool.version},
            )
        self._tools[key] = tool

    def resolve(self, name: str, version: str | None = None) -> AnyTool:
        """The named tool, at the requested version or the highest registered one."""
        if version is not None:
            tool = self._tools.get((name, version))
            if tool is None:
                raise ToolError(
                    "TOOL_NOT_FOUND",
                    f"no tool {name} at version {version}",
                    {"name": name, "version": version},
                )
            return tool

        versions = sorted(
            (parse_version(registered), registered)
            for registered_name, registered in self._tools
            if registered_name == name
        )
        if not versions:
            raise ToolError("TOOL_NOT_FOUND", f"no tool named {name}", {"name": name})
        return self._tools[(name, versions[-1][1])]

    def describe(self) -> list[ToolSpec]:
        """Machine-readable specs, in a stable order.

        Feeds plan validation, and in v2 the planner prompt. Sorted because a
        dict-iteration order leaking into a prompt would make the planner's
        output depend on import order.
        """
        return [type(tool).spec() for _, tool in sorted(self._tools.items())]

    def __contains__(self, name: object) -> bool:
        return any(registered == name for registered, _ in self._tools)

    def __len__(self) -> int:
        return len(self._tools)

"""CLI layer (frameworks tier).

The ``trading`` command-line entry point lives here. Per ADR §10.7, this
package is the composition root — it wires domain, use_cases, ports, and
adapters into a runnable program. ``trading`` itself is exposed via
``[project.scripts]`` in ``pyproject.toml`` and resolves to ``src.cli:main``;
the click group is defined in ``src.cli.main`` and re-exported below.
"""
from src.cli.main import main

__all__ = ["main"]

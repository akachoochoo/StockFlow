"""CLI layer (frameworks tier).

The ``trading`` command-line entry point lives here. Per ADR §10.7, this
package is the composition root — it wires domain, use_cases, ports, and
adapters into a runnable program. ``trading`` itself is exposed via
``[project.scripts]`` in ``pyproject.toml`` and points at
``src.cli.main:main``.
"""

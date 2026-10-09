"""The bundled adapters, one module per tool, and helpers for writing more (:mod:`.kit`).

Each Python adapter runs with the interpreter of an environment where its tool is installed, either
as its own module (``python -m lookml_conformance.adapters.datahub <project>...``) or by entry point
name (``python -m lookml_conformance.adapters datahub <project>...``).
"""

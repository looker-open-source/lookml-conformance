"""Adapters that run a LookML tool on a project and print its resolution in the protocol format.

Each Python adapter is a module run with the interpreter of an environment where its tool is
installed, for example ``python -m lookml_conformance.adapters.datahub <project>``. Shared helpers
live in :mod:`lookml_conformance.adapters.kit`.
"""

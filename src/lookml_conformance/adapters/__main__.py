"""Run an installed adapter by name: ``python -m lookml_conformance.adapters <name> <project>...``."""

import sys

from lookml_conformance.adapter import main

sys.exit(main())

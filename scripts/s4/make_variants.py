# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Write the S4 variant projects: four variants, each answering a second question its base case
cannot, and one negative control.

usage: python scripts/s4/make_variants.py <output_dir>

Each variant is a copy of a case's project/ with one change. Resolve them on Looker with the Looker
adapter (docs/looker-adapter.md):

    python -m lookml_conformance.adapters.looker --dump looker-dump <output_dir>/*

- s4-r04-swapped (from r04): the two includes in the other order. A negative control: r04
  resolves from_a, so this must resolve from_b, or the setup is not reading the pushed files.
- s4-r10b (from r10): the final refinement is included last. No error, and a.final?
- s4-r12b (from r12): adds explore: ghost {}. Does +ghost create a view an explore can use?
- s4-i01b (from i01): renames r/b_r.view.lkml to r/B_r.view.lkml. Byte order (from_a) or
  case-insensitive order (from_b)?
- s4-e01b (from e01): includes the refinement after the extending view. Does include position
  matter for inherited refinements?
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

CASES = Path(__file__).resolve().parents[2] / "cases"


def copy(case: str, out: Path, name: str) -> Path:
    target = out / name
    shutil.rmtree(target, ignore_errors=True)
    shutil.copytree(CASES / case / "project", target)
    return target


def main(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)

    swapped = copy("refinements/r04_later_include_wins", out, "s4-r04-swapped")
    (swapped / "m.model.lkml").write_text(
        'connection: "wh"\n'
        'include: "/orders.view"\n'
        'include: "/a.view.lkml"\n'
        'include: "/b.view.lkml"\n'
        "explore: orders {}\n"
    )

    r10b = copy("refinements/r10_final_refinement_blocks_later_ones", out, "s4-r10b")
    (r10b / "m.model.lkml").write_text(
        'connection: "wh"\n'
        'include: "/orders.view"\n'
        'include: "/r_later.view.lkml"\n'
        'include: "/r_final.view.lkml"\n'
        "explore: orders {}\n"
    )

    r12b = copy("refinements/r12_refinement_without_a_base_view", out, "s4-r12b")
    with (r12b / "m.model.lkml").open("a") as model:
        model.write("\nexplore: ghost {}\n")

    i01b = copy("includes/i01_wildcard_include_applies_in_path_order", out, "s4-i01b")
    (i01b / "r" / "b_r.view.lkml").rename(i01b / "r" / "B_r.view.lkml")

    e01b = copy("extends/e01_extends_inherits_the_refined_base", out, "s4-e01b")
    (e01b / "main.model.lkml").write_text(
        'connection: "wh"\n'
        'include: "/views/orders.view.lkml"\n'
        'include: "/views/ext.view.lkml"\n'
        'include: "/views/refine.view.lkml"\n'
        "explore: orders {}\n"
        "explore: orders_ext {}\n"
    )
    for path in sorted(out.iterdir()):
        print(path)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    main(Path(sys.argv[1]))

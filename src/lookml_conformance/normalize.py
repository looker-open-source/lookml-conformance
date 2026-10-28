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

"""Value normalization shared by the judge and the adapters."""

from __future__ import annotations

import re

_WHITESPACE = re.compile(r"\s+")


def collapse_whitespace(value: object) -> str | None:
    """Return ``value`` as a string with runs of whitespace collapsed to one space.

    ``None`` stays ``None`` so that "not set" and "empty" remain distinguishable.
    """
    if value is None:
        return None
    return _WHITESPACE.sub(" ", str(value)).strip()

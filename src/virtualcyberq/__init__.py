# SPDX-License-Identifier: BSD-3-Clause
"""VirtualCyberQ: a high-fidelity virtual/emulated BBQ Guru CyberQ WiFi device.

Importing this package is intentionally cheap and side-effect free. Heavier
submodules (``core``, ``xml``, ``web``, ``scenario``, ...) are imported directly
by consumers as they are built out; only ``__version__`` is exported here so
importing the package never fails while sibling modules are still in progress.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]

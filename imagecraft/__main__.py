"""Entry point for ``python -m imagecraft``."""

from __future__ import annotations

import sys

from imagecraft.main import main

if __name__ == "__main__":
    sys.exit(main())

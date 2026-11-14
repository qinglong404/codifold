"""Allow ``python -m codifold serve`` and the workbench commands."""
from .workbench import main

raise SystemExit(main())

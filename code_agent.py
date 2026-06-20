#!/usr/bin/env python3
"""code_agent — Launch the local-cli REPL.

This is the recommended entry point for desktop users.  It:

1. Ensures the ``.agents/`` directory exists with default identity files
2. Launches the interactive REPL with all identity features enabled
   (SOUL.md, USER.md, GENERAL.md, MEMORY.md)
3. Shows startup nudges for pending proposals and missing files

Usage:
    python -m code_agent                       # Launch with default model
    python -m code_agent --model qwen3:8b      # Launch with specific model
    python -m code_agent --debug               # Launch with debug output
"""

from __future__ import annotations

import os
import sys


def main() -> None:
    """Entry point for the code_agent module.

    Ensures identity files exist, then launches the full REPL.
    """
    # 1. Ensure identity files exist before launching the REPL.
    from local_cli.config import Config
    from local_cli.identity import IdentityLoader

    # Build a minimal config to get the default agents_dir and state_dir.
    config = Config()

    loader = IdentityLoader(
        agents_dir=config.agents_dir,
        state_dir=config.state_dir,
    )
    created = loader.ensure_agents_dir()
    if created:
        print(f"[code_agent] Created {len(created)} identity file(s) in {config.agents_dir}/")
        for fname in created:
            print(f"  - {fname}")
        print()

    # 2. Forward all CLI arguments to the main entry point.
    from local_cli.__main__ import main as cli_main
    cli_main()


if __name__ == "__main__":
    # Add project root to the Python path when running directly as a script.
    _project_root = os.path.dirname(os.path.abspath(__file__))
    if _project_root not in sys.path:
        sys.path.insert(0, _project_root)
    main()

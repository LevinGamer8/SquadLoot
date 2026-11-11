#!/usr/bin/env python3
"""Small launcher: checks/install updates before loading the main GUI."""
# A separate developer beta must never apply the Pi's production updates.
import os
if os.getenv('SQUADLOOT_BETA_TEST') != '1':
    from update_manager import startup_update
    startup_update()
from app import main
if __name__ == '__main__':
    main()

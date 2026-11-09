#!/usr/bin/env python3
"""Small launcher: checks/install updates before loading the main GUI."""
from update_manager import startup_update
startup_update()
from app import main
if __name__ == '__main__':
    main()

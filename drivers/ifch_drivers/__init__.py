# Copyright (c) 2026-2026, ISIA Lab (UMONS)
# SPDX-License-Identifier: Apache-2.0

# iFCH Devices Drivers Package
"""
Common drivers and utilities for iFCH devices.
"""

__version__ = "1.0"

from .utils import BoundedQueue

__all__ = ["__version__", "BoundedQueue"]

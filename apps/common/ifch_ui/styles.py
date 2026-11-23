# Copyright (c) 2026-2026, ISIA Lab (UMONS)
# SPDX-License-Identifier: GPL-3.0-only

"""Shared colors, dimensions, and style definitions."""

from dataclasses import dataclass

from PySide6.QtCore import Qt

GREEN_L = "#4caf50"
GREEN_M = "#378039"
GREEN_D = "#214d22"

ORANGE_L = "#b0974c"
ORANGE_M = "#806d37"
ORANGE_D = "#4d4121"

RED_L = "#af4c4c"
RED_M = "#803737"
RED_D = "#4d2121"

PURPLE_L = "#654cb0"
PURPLE_M = "#493780"
PURPLE_D = "#2c214d"

BLUE_L = "#4c82af"
BLUE_M = "#375f80"
BLUE_D = "#21394d"

GREY_L = "#b0b0b0"
GREY_M = "#808080"
GREY_D = "#4d4d4d"

ECG_COLOR = "#CC3311"
ACC_COLOR = "#0077BB"


@dataclass
class ButtonStyle:
    """Style configuration for buttons."""

    color_light: str
    color_medium: str
    color_dark: str
    font_size: int = 16
    font_weight: str = "regular"
    padding: str = "10px 30px"
    border_radius: str = "4px"


@dataclass
class LabelStyle:
    """Style configuration for labels."""

    color: str
    font_size: int
    font_weight: str = "normal"
    alignment: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignCenter


GREY_BUTTON = ButtonStyle(GREY_L, GREY_M, GREY_D)
ORANGE_BUTTON = ButtonStyle(ORANGE_L, ORANGE_M, ORANGE_D)
GREEN_BUTTON = ButtonStyle(GREEN_L, GREEN_M, GREEN_D)
RED_BUTTON = ButtonStyle(RED_L, RED_M, RED_D)
PURPLE_BUTTON = ButtonStyle(PURPLE_L, PURPLE_M, PURPLE_D)
BLUE_BUTTON = ButtonStyle(BLUE_L, BLUE_M, BLUE_D)

TITLE_SPACING = 30
BUTTON_SPACING = 20

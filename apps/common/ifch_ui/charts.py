# Copyright (c) 2026-2026, ISIA Lab (UMONS)
# SPDX-License-Identifier: GPL-3.0-only

"""Reusable live chart widgets."""

from PySide6.QtCharts import QChart, QChartView, QLineSeries, QValueAxis
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QVBoxLayout, QWidget


class LineChart(QWidget):
    """Single-series chart with hidden axes for live monitoring."""

    def __init__(
        self,
        *,
        series_name: str,
        series_color: QColor,
        x_range: tuple[float, float],
        y_axis_title: str,
        x_axis_title: str = "",
        chart_title: str = "",
        show_x_grid: bool = True,
        minimum_width: int = 500,
    ):
        super().__init__()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.series = QLineSeries()
        self.series.setName(series_name)
        pen = self.series.pen()
        pen.setWidth(1)
        pen.setColor(series_color)
        self.series.setPen(pen)

        self.chart = QChart()
        self.chart.addSeries(self.series)
        if chart_title:
            self.chart.setTitle(chart_title)

        self.axis_x = QValueAxis()
        self.axis_x.setRange(*x_range)
        self.axis_x.setGridLineVisible(show_x_grid)
        self.axis_x.setVisible(False)
        if x_axis_title:
            self.axis_x.setTitleText(x_axis_title)

        self.axis_y = QValueAxis()
        self.axis_y.setTitleText(y_axis_title)
        self.axis_y.setRange(-1, 1)
        self.axis_y.setVisible(False)

        self.chart.addAxis(self.axis_x, Qt.AlignmentFlag.AlignBottom)
        self.chart.addAxis(self.axis_y, Qt.AlignmentFlag.AlignLeft)
        self.chart.legend().setVisible(False)
        self.series.attachAxis(self.axis_x)
        self.series.attachAxis(self.axis_y)

        self.chart_view = QChartView(self.chart)
        self.chart_view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.chart_view.setMinimumWidth(minimum_width)
        layout.addWidget(self.chart_view)

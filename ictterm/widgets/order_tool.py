"""TradingView-style draggable long/short position tool for pyqtgraph."""
from __future__ import annotations

from typing import Any

import pyqtgraph as pg
from pyqtgraph.Qt import QtCore, QtWidgets

from .. import config


class PositionTool:
    """A draggable risk/reward box with entry, stop and target handles."""

    def __init__(self, plot: pg.PlotItem, x0: float, x1: float, entry: float, stop: float,
                 target: float, direction: str, digits: int = 2, auto: bool = False,
                 tag: str = "") -> None:
        self.plot = plot
        self.digits = digits
        self.direction = direction
        self.auto = auto
        self.tag = tag
        self.items: list[Any] = []
        self.entry = float(entry)
        self.stop = float(stop)
        self.target = float(target)
        self.x0 = float(x0)
        self.x1 = float(x1)

        self.risk_rect = QtWidgets.QGraphicsRectItem()
        self.reward_rect = QtWidgets.QGraphicsRectItem()
        self.risk_rect.setZValue(-8)
        self.reward_rect.setZValue(-9)
        self.risk_rect.setPen(pg.mkPen((239, 83, 80, 90), width=0.8, style=QtCore.Qt.PenStyle.DashLine))
        self.reward_rect.setPen(pg.mkPen((38, 166, 154, 90), width=0.8, style=QtCore.Qt.PenStyle.DashLine))
        self.risk_rect.setBrush(pg.mkBrush(config.ORDER_SHORT_FILL))
        self.reward_rect.setBrush(pg.mkBrush(config.ORDER_LONG_FILL))
        self.plot.addItem(self.risk_rect)
        self.plot.addItem(self.reward_rect)
        self.items += [self.risk_rect, self.reward_rect]

        accent = config.ORDER_LONG_LINE if direction == "long" else config.ORDER_SHORT_LINE
        self.entry_line = self._hline(self.entry, config.ACCENT, "Entry", 1.4, position=0.86)
        self.stop_line = self._hline(self.stop, config.BEAR, "SL", 1.1, position=0.86, dash=True)
        self.target_line = self._hline(self.target, config.BULL, "TP", 1.1, position=0.86, dash=True)
        self.left_line = self._vline(self.x0)
        self.right_line = self._vline(self.x1)
        self.rr_label = pg.TextItem("", color=accent, anchor=(1.0, 0.5), fill=(11, 15, 20, 210))
        self.rr_label.setZValue(25)
        self.plot.addItem(self.rr_label)
        self.items.append(self.rr_label)

        for line in (self.entry_line, self.stop_line, self.target_line, self.left_line, self.right_line):
            line.sigDragged.connect(self._update)

        self._update()

    # ------------------------------------------------------------------ items
    def _hline(self, pos: float, color: str, name: str, width: float,
               position: float = 0.9, dash: bool = False) -> pg.InfiniteLine:
        pen = pg.mkPen(color, width=width, style=QtCore.Qt.PenStyle.DashLine if dash else QtCore.Qt.PenStyle.SolidLine)
        hover = pg.mkPen("#ffffff", width=width + 0.8)
        line = pg.InfiniteLine(
            pos=float(pos), angle=0, movable=True, pen=pen, hoverPen=hover,
            label=f"{name} {pos:,.{self.digits}f}",
            labelOpts={"position": position, "color": color, "fill": (11, 15, 20, 220),
                       "movable": False},
        )
        line.setZValue(20)
        try:
            line.label.setFont(QtWidgets.QApplication.font())
        except Exception:
            pass
        self.plot.addItem(line)
        self.items.append(line)
        return line

    def _vline(self, pos: float) -> pg.InfiniteLine:
        line = pg.InfiniteLine(
            pos=float(pos), angle=90, movable=True,
            pen=pg.mkPen((130, 150, 175, 70), width=1.0, style=QtCore.Qt.PenStyle.DotLine),
            hoverPen=pg.mkPen(config.ACCENT, width=1.6),
        )
        line.setZValue(19)
        self.plot.addItem(line)
        self.items.append(line)
        return line

    # ----------------------------------------------------------------- update
    def _update(self) -> None:
        self.entry = float(self.entry_line.value())
        self.stop = float(self.stop_line.value())
        self.target = float(self.target_line.value())
        self.x0 = float(self.left_line.value())
        self.x1 = float(self.right_line.value())
        if self.x1 < self.x0:
            self.x0, self.x1 = self.x1, self.x0
        width = max(self.x1 - self.x0, 0.6)
        for rect, top, bottom in (
            (self.risk_rect, self.entry, self.stop),
            (self.reward_rect, self.entry, self.target),
        ):
            rect.setRect(self.x0, min(top, bottom), width, abs(top - bottom))
        self._set_label(self.entry_line, f"Entry {self.entry:,.{self.digits}f}", config.ACCENT)
        self._set_label(self.stop_line, f"SL {self.stop:,.{self.digits}f}", config.BEAR)
        self._set_label(self.target_line, f"TP {self.target:,.{self.digits}f}", config.BULL)

        if self.direction == "long":
            risk = self.entry - self.stop
            reward = self.target - self.entry
        else:
            risk = self.stop - self.entry
            reward = self.entry - self.target
        rr = (reward / risk) if risk > 1e-12 else 0.0
        valid = risk > 0 and reward > 0
        label = f"{self.direction.upper()}"
        if valid:
            label += f"  ·  R:R {rr:.2f}"
        else:
            label += "  ·  invalid SL/TP"
        if self.auto:
            label += "\nforecast"
        color = config.ORDER_LONG_LINE if self.direction == "long" else config.ORDER_SHORT_LINE
        if not valid:
            color = config.GOLD
        self.rr_label.setColor(color)
        self.rr_label.setText(label)
        self.rr_label.setPos(self.x1 + 0.8, (self.entry + self.target) / 2)

    @staticmethod
    def _set_label(line: pg.InfiniteLine, text: str, color: str) -> None:
        try:
            line.label.setText(text)
            line.label.setColor(color)
        except Exception:
            pass

    # ------------------------------------------------------------------ misc
    def remove(self) -> None:
        for item in self.items:
            try:
                self.plot.removeItem(item)
            except Exception:
                pass
        self.items.clear()

    def set_visible(self, visible: bool) -> None:
        for item in self.items:
            try:
                item.setVisible(visible)
            except Exception:
                pass

    def to_dict(self) -> dict:
        return {
            "x0": self.x0, "x1": self.x1, "entry": self.entry,
            "stop": self.stop, "target": self.target,
            "direction": self.direction, "auto": self.auto,
        }

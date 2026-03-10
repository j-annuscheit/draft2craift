from __future__ import annotations

from typing import Callable, Optional, TypedDict

BBox = tuple[float, float, float, float]
ComputeBodyFontSize = Callable[[object, float, float], float]
ExtractTableBBoxes = Callable[[object], list[BBox]]
RectIntersectionRatio = Callable[[BBox, BBox], float]

GroupKey = tuple[str, str, str]
PairKey = tuple[Optional[GroupKey], Optional[GroupKey]]


class GroupOccurrence(TypedDict):
    page: int
    bbox: BBox
    page_h: float
    y0: float
    y1: float
    x_metric: float
    y_metric: float
    h_ratio: float
    had_page: bool
    had_heading: bool


GroupOccMap = dict[GroupKey, list[GroupOccurrence]]
GroupDisplayMap = dict[GroupKey, str]
PageChoiceMap = dict[int, tuple[GroupKey, float, BBox]]
PairPagesMap = dict[PairKey, list[int]]
PairSamplesMap = dict[PairKey, list[float]]
PairPrototypesMap = dict[PairKey, tuple[float, float]]
PageAssignmentMap = dict[int, PairKey]
RectsByPage = dict[int, dict[str, list[BBox]]]

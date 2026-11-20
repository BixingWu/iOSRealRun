"""Named WGS 84 drawing documents in the user's local route library."""

import json
import math
import re
import uuid
from dataclasses import dataclass

from iosrealrun.desktop_routes import MAX_ROUTE_BYTES, MAX_ROUTE_POINTS, _normalize_points, write_route_json
from iosrealrun.route_drawing import SHAPES


MAX_DRAFT_BYTES = 4 * MAX_ROUTE_BYTES


@dataclass
class DrawingDraft:
    title: str
    venue: str
    shape: str
    points: list
    corners: list
    reference: list
    closed: bool
    smoothing: bool
    show_reference: bool
    lettering_direction: str
    field_angle: float | None
    rotation: float
    reference_venue: str = ""

    @classmethod
    def from_document(cls, data):
        if not isinstance(data, dict) or data.get("format") != 1:
            raise ValueError("无法识别草稿格式。")
        try:
            draft = cls(**{key: value for key, value in data.items() if key != "format"})
        except TypeError as error:
            raise ValueError("草稿缺少绘制数据。") from error
        for name in ("title", "venue", "reference_venue"):
            value = getattr(draft, name)
            if not isinstance(value, str) or len(value) > 160 or (not value.strip() and name != "reference_venue"):
                raise ValueError("请输入场地和草稿名称，最长 160 字。")
            setattr(draft, name, value.strip())
        if draft.shape not in ("", *SHAPES) or draft.lettering_direction not in ("auto", "horizontal", "vertical"):
            raise ValueError("草稿的绘制方式无效。")
        if any(type(flag) is not bool for flag in (draft.closed, draft.smoothing, draft.show_reference)):
            raise ValueError("草稿的绘制选项无效。")
        angles = [draft.rotation] if draft.field_angle is None else [draft.rotation, draft.field_angle]
        if any(type(angle) not in (int, float) or not math.isfinite(angle) for angle in angles):
            raise ValueError("草稿方向无效。")
        for name in ("points", "corners", "reference"):
            points = getattr(draft, name)
            if not isinstance(points, list) or (name == "corners" and len(points) > 2):
                raise ValueError("草稿坐标无效。")
            # A full-size closed reference may carry one extra copy of its start.
            extra_end = name == "reference" and len(points) == MAX_ROUTE_POINTS + 1 and points[0] == points[-1]
            points = _normalize_points(points[:-1] if extra_end else points, preserve_endpoint=True, minimum=0)
            if extra_end:
                points.extend(points[:1])
            setattr(draft, name, points)
        return draft


def _draft_path(directory, identifier):
    if not isinstance(identifier, str) or not re.fullmatch(r"[0-9a-f]{32}", identifier):
        raise ValueError("草稿编号无效。")
    return directory / f"{identifier}.json"


def save_draft(directory, draft, identifier=None):
    identifier = uuid.uuid4().hex if identifier is None else identifier
    data = {"format": 1, **vars(draft)}
    checked = DrawingDraft.from_document(data)
    write_route_json(_draft_path(directory, identifier), {"format": 1, **vars(checked)}, MAX_DRAFT_BYTES)
    return identifier


def load_draft(directory, identifier):
    with _draft_path(directory, identifier).open("rb") as file:
        payload = file.read(MAX_DRAFT_BYTES + 1)
    if len(payload) > MAX_DRAFT_BYTES:
        raise ValueError("草稿文件太大。")
    return DrawingDraft.from_document(json.loads(payload))


def draft_catalog(directory):
    rows = []
    for path in directory.glob("*.json"):
        try:
            draft = load_draft(directory, path.stem)
        except (OSError, ValueError, OverflowError, RecursionError):
            continue
        rows.append((draft.venue, draft.title, path.stem))
    return sorted(rows, key=lambda row: (row[0].casefold(), row[1].casefold(), row[2]))

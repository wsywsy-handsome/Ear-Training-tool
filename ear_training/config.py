from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class ChordPattern:
    name: str
    label: str
    intervals: tuple[int, ...]
    group: str = "custom"


def load_patterns(path: str | Path) -> dict[str, ChordPattern]:
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as file:
        raw = yaml.safe_load(file) or {}

    chords = raw.get("chords")
    if not isinstance(chords, dict):
        raise ValueError(f"{config_path} must contain a top-level 'chords' mapping")

    patterns: dict[str, ChordPattern] = {}
    for name, spec in chords.items():
        patterns[str(name)] = _parse_pattern(str(name), spec)
    return patterns


def _parse_pattern(name: str, spec: Any) -> ChordPattern:
    if not isinstance(spec, dict):
        raise ValueError(f"Chord '{name}' must be a mapping")

    intervals = spec.get("intervals")
    if not isinstance(intervals, list) or not intervals:
        raise ValueError(f"Chord '{name}' must define a non-empty intervals list")

    parsed_intervals: list[int] = []
    for value in intervals:
        if not isinstance(value, int):
            raise ValueError(f"Chord '{name}' has a non-integer interval: {value!r}")
        if value < 0:
            raise ValueError(f"Chord '{name}' has a negative interval: {value}")
        parsed_intervals.append(value)

    if 0 not in parsed_intervals:
        raise ValueError(f"Chord '{name}' must include interval 0 for the root")

    label = spec.get("label", name)
    group = spec.get("group", "custom")
    return ChordPattern(
        name=name,
        label=str(label),
        intervals=tuple(parsed_intervals),
        group=str(group),
    )

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import random
import re

from ear_training.config import ChordPattern


NOTE_TO_PC = {
    "C": 0,
    "B#": 0,
    "C#": 1,
    "DB": 1,
    "D": 2,
    "D#": 3,
    "EB": 3,
    "E": 4,
    "FB": 4,
    "E#": 5,
    "F": 5,
    "F#": 6,
    "GB": 6,
    "G": 7,
    "G#": 8,
    "AB": 8,
    "A": 9,
    "A#": 10,
    "BB": 10,
    "B": 11,
    "CB": 11,
}

PC_TO_NAME = {
    0: "C",
    1: "C#",
    2: "D",
    3: "Eb",
    4: "E",
    5: "F",
    6: "F#",
    7: "G",
    8: "Ab",
    9: "A",
    10: "Bb",
    11: "B",
}

NOTE_RE = re.compile(r"^([A-Ga-g])([#bB]?)(-?\d+)$")


@dataclass(frozen=True)
class Exercise:
    root: int
    pattern: ChordPattern

    @property
    def notes(self) -> tuple[int, ...]:
        return tuple(self.root + interval for interval in self.pattern.intervals)

    @property
    def pitch_classes(self) -> Counter[int]:
        return pitch_class_counter(self.notes)

    @property
    def prompt(self) -> str:
        return f"{midi_to_note_name(self.root)} {self.pattern.label}"


@dataclass(frozen=True)
class AnswerResult:
    correct: bool
    expected: tuple[str, ...]
    heard: tuple[str, ...]
    missing: tuple[str, ...]
    extra: tuple[str, ...]


def parse_note_name(name: str) -> int:
    match = NOTE_RE.match(name.strip())
    if not match:
        raise ValueError(f"Invalid note name: {name!r}. Expected format like C4 or Bb3.")

    letter, accidental, octave_text = match.groups()
    pitch_name = f"{letter.upper()}{accidental.upper()}"
    octave = int(octave_text)
    return (octave + 1) * 12 + NOTE_TO_PC[pitch_name]


def midi_to_note_name(note: int) -> str:
    if not 0 <= note <= 127:
        raise ValueError(f"MIDI note out of range: {note}")
    octave = note // 12 - 1
    return f"{PC_TO_NAME[note % 12]}{octave}"


def pitch_class_names(values: Counter[int] | set[int]) -> tuple[str, ...]:
    names: list[str] = []
    for pc in sorted(values):
        count = values[pc] if isinstance(values, Counter) else 1
        names.extend(PC_TO_NAME[pc] for _ in range(count))
    return tuple(names)


def pitch_class_counter(notes: tuple[int, ...] | list[int] | set[int]) -> Counter[int]:
    return Counter(note % 12 for note in notes)


def choose_exercise(
    patterns: dict[str, ChordPattern],
    chord_names: list[str] | None,
    root_low: int,
    root_high: int,
    rng: random.Random,
) -> Exercise:
    selected_names = chord_names or list(patterns)
    missing = [name for name in selected_names if name not in patterns]
    if missing:
        raise ValueError(f"Unknown chord pattern(s): {', '.join(missing)}")

    pattern = patterns[rng.choice(selected_names)]
    max_interval = max(pattern.intervals)
    high = min(root_high, 127 - max_interval)
    if root_low > high:
        raise ValueError("Root range is too high for the selected chord patterns")
    return Exercise(root=rng.randint(root_low, high), pattern=pattern)


def parse_root_range(value: str) -> tuple[int, int]:
    if ":" not in value:
        note = parse_note_name(value)
        return note, note

    low_text, high_text = value.split(":", 1)
    low = parse_note_name(low_text)
    high = parse_note_name(high_text)
    if low > high:
        raise ValueError("Root range low note must be <= high note")
    return low, high


def judge_answer(expected_notes: tuple[int, ...], played_notes: tuple[int, ...]) -> AnswerResult:
    expected = {note % 12 for note in expected_notes}
    heard = {note % 12 for note in played_notes}
    missing = expected - heard
    extra = heard - expected
    return AnswerResult(
        correct=not missing and not extra,
        expected=pitch_class_names(expected),
        heard=pitch_class_names(heard),
        missing=pitch_class_names(missing),
        extra=pitch_class_names(extra),
    )

from __future__ import annotations

import time
from typing import Iterable

import mido


def list_ports() -> tuple[list[str], list[str]]:
    return mido.get_input_names(), mido.get_output_names()


def open_input(name: str | None):
    return mido.open_input(name) if name else mido.open_input()


def open_output(name: str | None):
    return mido.open_output(name) if name else mido.open_output()


def play_chord(
    output,
    notes: Iterable[int],
    velocity: int = 80,
    duration: float = 1.6,
    channel: int = 0,
) -> None:
    note_list = list(notes)
    for note in note_list:
        output.send(mido.Message("note_on", note=note, velocity=velocity, channel=channel))
    time.sleep(duration)
    for note in note_list:
        output.send(mido.Message("note_off", note=note, velocity=0, channel=channel))


def collect_answer(
    midi_input,
    answer_window: float,
    quiet_after: float,
    channel: int | None = None,
) -> tuple[int, ...]:
    started_at = time.monotonic()
    last_note_at: float | None = None
    pressed: set[int] = set()
    captured: list[int] = []

    while time.monotonic() - started_at < answer_window:
        saw_message = False
        for message in midi_input.iter_pending():
            saw_message = True
            if channel is not None and getattr(message, "channel", None) != channel:
                continue

            if message.type == "note_on" and message.velocity > 0:
                pressed.add(message.note)
                captured.append(message.note)
                last_note_at = time.monotonic()
            elif message.type in {"note_off", "note_on"}:
                pressed.discard(message.note)
                if captured:
                    last_note_at = time.monotonic()

        if captured and not pressed and last_note_at is not None:
            if time.monotonic() - last_note_at >= quiet_after:
                break

        if not saw_message:
            time.sleep(0.01)

    return tuple(captured)


def drain_pending(midi_input) -> None:
    for _message in midi_input.iter_pending():
        pass


def panic(output, channel: int = 0) -> None:
    for note in range(128):
        output.send(mido.Message("note_off", note=note, velocity=0, channel=channel))

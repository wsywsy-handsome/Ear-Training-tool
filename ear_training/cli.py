from __future__ import annotations

import argparse
from pathlib import Path
import random
import sys

from ear_training.config import load_patterns
from ear_training.midi_io import (
    collect_answer,
    drain_pending,
    list_ports,
    open_input,
    open_output,
    panic,
    play_chord,
)
from ear_training.music import choose_exercise, judge_answer, parse_root_range


DEFAULT_CONFIG = Path(__file__).resolve().with_name("chords.yaml")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\nStopped.")
        return 130
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ear-training")
    subparsers = parser.add_subparsers(required=True)

    ports_parser = subparsers.add_parser("list-ports", help="Show available MIDI ports")
    ports_parser.set_defaults(func=cmd_list_ports)

    monitor_parser = subparsers.add_parser("monitor", help="Print incoming MIDI note messages")
    monitor_parser.add_argument("--input", help="MIDI input port name")
    monitor_parser.add_argument("--input-channel", type=int, help="MIDI channel, 1-16; default listens to all")
    monitor_parser.set_defaults(func=cmd_monitor)

    gui_parser = subparsers.add_parser("gui", help="Start the visual chord recognition drill")
    gui_parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="Path to chords YAML")
    gui_parser.add_argument("--input", help="MIDI input port name")
    gui_parser.add_argument("--output", help="MIDI output port name")
    gui_parser.add_argument("--chords", nargs="+", help="Chord pattern names to include")
    gui_parser.add_argument("--root-range", default="C3:C5", help="Root range, e.g. C3:C5")
    gui_parser.add_argument("--keyboard-range", default="C4:B5", help="Displayed keyboard range, e.g. C4:B5")
    gui_parser.add_argument("--rounds", type=int, default=10, help="Number of rounds")
    gui_parser.add_argument("--forever", action="store_true", help="Keep asking until the window closes")
    gui_parser.add_argument("--seed", type=int, help="Random seed")
    gui_parser.add_argument("--quiet-after", type=float, default=0.7, help="Judge after this much silence")
    gui_parser.add_argument("--duration", type=float, default=1.6, help="Chord playback duration")
    gui_parser.add_argument("--velocity", type=int, default=80, help="Playback velocity")
    gui_parser.add_argument("--output-channel", type=int, default=1, help="Playback MIDI channel, 1-16")
    gui_parser.add_argument("--input-channel", type=int, help="Answer MIDI channel, 1-16; default listens to all")
    gui_parser.add_argument("--next-delay", type=float, default=1.8, help="Seconds to show the answer before next round")
    gui_parser.set_defaults(func=cmd_gui)

    drill_parser = subparsers.add_parser("drill", help="Start a chord recognition drill")
    drill_parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="Path to chords YAML")
    drill_parser.add_argument("--input", help="MIDI input port name")
    drill_parser.add_argument("--output", help="MIDI output port name")
    drill_parser.add_argument("--chords", nargs="+", help="Chord pattern names to include")
    drill_parser.add_argument("--root-range", default="C3:C5", help="Root range, e.g. C3:C5")
    drill_parser.add_argument("--rounds", type=int, default=10, help="Number of rounds")
    drill_parser.add_argument("--forever", action="store_true", help="Keep asking until Ctrl-C")
    drill_parser.add_argument("--require-correct", action="store_true", help="Repeat each question until answered correctly")
    drill_parser.add_argument("--seed", type=int, help="Random seed")
    drill_parser.add_argument("--answer-window", type=float, default=8.0, help="Seconds to wait for MIDI answer")
    drill_parser.add_argument("--quiet-after", type=float, default=0.7, help="Stop after this much silence")
    drill_parser.add_argument("--duration", type=float, default=1.6, help="Chord playback duration")
    drill_parser.add_argument("--velocity", type=int, default=80, help="Playback velocity")
    drill_parser.add_argument("--output-channel", type=int, default=1, help="Playback MIDI channel, 1-16")
    drill_parser.add_argument("--input-channel", type=int, help="Answer MIDI channel, 1-16; default listens to all")
    drill_parser.add_argument("--show-answer", action="store_true", help="Print chord name after each round")
    drill_parser.set_defaults(func=cmd_drill)

    return parser


def cmd_list_ports(_args: argparse.Namespace) -> int:
    inputs, outputs = list_ports()
    _say("MIDI inputs:")
    for index, name in enumerate(inputs, 1):
        _say(f"  {index}. {name}")
    if not inputs:
        _say("  (none)")

    _say("\nMIDI outputs:")
    for index, name in enumerate(outputs, 1):
        _say(f"  {index}. {name}")
    if not outputs:
        _say("  (none)")
    return 0


def cmd_monitor(args: argparse.Namespace) -> int:
    input_channel = _parse_channel(args.input_channel, "--input-channel") if args.input_channel is not None else None
    _say("Opening MIDI input...")
    with open_input(args.input) as midi_input:
        _say(f"Listening on: {midi_input.name}")
        _say("Press keys on your MIDI keyboard. Ctrl-C to stop.")
        while True:
            for message in midi_input.iter_pending():
                if input_channel is not None and getattr(message, "channel", None) != input_channel:
                    continue
                if message.type in {"note_on", "note_off"}:
                    velocity = getattr(message, "velocity", 0)
                    _say(f"{message.type:8} note={message.note:3} velocity={velocity:3}")
            import time

            time.sleep(0.01)


def cmd_gui(args: argparse.Namespace) -> int:
    _parse_channel(args.output_channel, "--output-channel")
    if args.input_channel is not None:
        _parse_channel(args.input_channel, "--input-channel")
    patterns = load_patterns(args.config)
    parse_root_range(args.root_range)
    parse_root_range(args.keyboard_range)
    from ear_training.gui import run_gui

    return run_gui(args, patterns)


def cmd_drill(args: argparse.Namespace) -> int:
    patterns = load_patterns(args.config)
    root_low, root_high = parse_root_range(args.root_range)
    rng = random.Random(args.seed)
    output_channel = _parse_channel(args.output_channel, "--output-channel")
    input_channel = _parse_channel(args.input_channel, "--input-channel") if args.input_channel is not None else None

    _say("Opening MIDI ports...")
    with open_input(args.input) as midi_input, open_output(args.output) as midi_output:
        _say(f"Input:  {midi_input.name}")
        _say(f"Output: {midi_output.name}")
        if midi_input.name == midi_output.name:
            _say("Note: input and output are the same MIDI device. Many controller keyboards do not make sound from MIDI sent back to them.")
        first_try_correct = 0
        completed = 0
        try:
            round_number = 1
            while args.forever or round_number <= args.rounds:
                exercise = choose_exercise(patterns, args.chords, root_low, root_high, rng)
                if _ask_until_done(
                    args,
                    midi_input,
                    midi_output,
                    exercise,
                    round_number,
                    output_channel,
                    input_channel,
                ):
                    first_try_correct += 1
                completed += 1
                round_number += 1
        finally:
            panic(midi_output, channel=output_channel)
            _say(f"\nCompleted: {completed}")
            _say(f"First-try correct: {first_try_correct}/{completed}")
    return 0


def _ask_until_done(
    args: argparse.Namespace,
    midi_input,
    midi_output,
    exercise,
    round_number: int,
    output_channel: int,
    input_channel: int | None,
) -> bool:
    attempt = 1
    while True:
        _say(_round_label(round_number, args.rounds, args.forever, attempt, args.require_correct))
        _say("Listen...")
        play_chord(
            midi_output,
            exercise.notes,
            velocity=args.velocity,
            duration=args.duration,
            channel=output_channel,
        )
        drain_pending(midi_input)
        _say("Play your answer.")
        played = collect_answer(
            midi_input,
            answer_window=args.answer_window,
            quiet_after=args.quiet_after,
            channel=input_channel,
        )
        result = judge_answer(exercise.notes, played)
        if result.correct:
            _say("Correct.")
            if args.show_answer:
                _say(f"  Chord:    {exercise.prompt}")
            return attempt == 1

        _say("Not quite.")
        _say(f"  Expected: {', '.join(result.expected)}")
        _say(f"  Heard:    {_format_notes(result.heard)}")
        if result.missing:
            _say(f"  Missing:  {', '.join(result.missing)}")
        if result.extra:
            _say(f"  Extra:    {', '.join(result.extra)}")
        if args.show_answer:
            _say(f"  Chord:    {exercise.prompt}")

        if not args.require_correct:
            return False

        attempt += 1
        _say("Try the same chord again.")


def _parse_channel(value: int, flag: str) -> int:
    if not 1 <= value <= 16:
        raise ValueError(f"{flag} must be between 1 and 16")
    return value - 1


def _format_notes(notes: tuple[str, ...]) -> str:
    return ", ".join(notes) if notes else "(none)"


def _round_label(round_number: int, rounds: int, forever: bool, attempt: int, require_correct: bool) -> str:
    total = "forever" if forever else str(rounds)
    label = f"\nRound {round_number}/{total}"
    if require_correct and attempt > 1:
        label += f" attempt {attempt}"
    return label


def _say(message: str) -> None:
    print(message, flush=True)


if __name__ == "__main__":
    raise SystemExit(main())

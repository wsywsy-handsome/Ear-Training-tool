from __future__ import annotations

import random
import tkinter as tk
from dataclasses import dataclass
from tkinter import messagebox, ttk

from ear_training.config import ChordPattern
from ear_training.midi_io import drain_pending, open_input, open_output, panic
from ear_training.music import Exercise, choose_exercise, judge_answer, midi_to_note_name, parse_root_range


WHITE_PCS = {0, 2, 4, 5, 7, 9, 11}
BLACK_PCS = {1, 3, 6, 8, 10}


@dataclass(frozen=True)
class KeyGeometry:
    note: int
    rect_id: int
    text_id: int | None
    is_black: bool


class EarTrainingApp:
    def __init__(self, args, patterns: dict[str, ChordPattern]) -> None:
        self.args = args
        self.patterns = patterns
        self.root_low, self.root_high = parse_root_range(args.root_range)
        self.keyboard_low, self.keyboard_high = parse_root_range(args.keyboard_range)
        self.rng = random.Random(args.seed)
        self.output_channel = args.output_channel - 1
        self.input_channel = args.input_channel - 1 if args.input_channel is not None else None

        self.midi_input = open_input(args.input)
        self.midi_output = open_output(args.output)

        self.root = tk.Tk()
        self.root.title("Ear Training")
        self.root.geometry("1120x420")
        self.root.minsize(760, 360)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        self.exercise: Exercise | None = None
        self.round_number = 0
        self.first_try_correct = 0
        self.completed = 0
        self.attempt = 1
        self.pressed_notes: set[int] = set()
        self.captured_notes: list[int] = []
        self.revealed_notes: set[int] = set()
        self.revealed_answer = False
        self.accepting_answer = False
        self.after_next_id: str | None = None
        self.after_judge_id: str | None = None

        self.keys: dict[int, KeyGeometry] = {}
        self.white_key_width = 0
        self.key_height = 0

        self._build_ui()
        self._draw_keyboard()
        self._new_round()
        self._poll_midi()

    def run(self) -> None:
        self.root.mainloop()

    def close(self) -> None:
        if self.after_next_id is not None:
            self.root.after_cancel(self.after_next_id)
            self.after_next_id = None
        if self.after_judge_id is not None:
            self.root.after_cancel(self.after_judge_id)
            self.after_judge_id = None
        try:
            panic(self.midi_output, channel=self.output_channel)
            self.midi_input.close()
            self.midi_output.close()
        finally:
            self.root.destroy()

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        top = ttk.Frame(self.root, padding=(14, 12, 14, 8))
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(1, weight=1)

        self.status_var = tk.StringVar()
        self.score_var = tk.StringVar()
        self.answer_var = tk.StringVar()

        ttk.Label(top, textvariable=self.status_var, font=("Helvetica", 18, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(top, textvariable=self.score_var).grid(row=1, column=0, sticky="w", pady=(4, 0))
        ttk.Label(top, textvariable=self.answer_var).grid(row=0, column=1, rowspan=2, sticky="e")

        controls = ttk.Frame(top)
        controls.grid(row=0, column=2, rowspan=2, sticky="e", padx=(18, 0))
        ttk.Button(controls, text="重听", command=self._replay).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(controls, text="显示答案", command=self._show_answer).grid(row=0, column=1)

        self.canvas = tk.Canvas(self.root, bg="#f4f1eb", highlightthickness=0)
        self.canvas.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0, 14))
        self.canvas.bind("<Configure>", lambda _event: self._draw_keyboard())

    def _new_round(self) -> None:
        if self.after_next_id is not None:
            self.root.after_cancel(self.after_next_id)
            self.after_next_id = None
        if self.after_judge_id is not None:
            self.root.after_cancel(self.after_judge_id)
            self.after_judge_id = None
        if not self.args.forever and self.completed >= self.args.rounds:
            self.accepting_answer = False
            self._set_status("Done")
            return
        self.round_number += 1
        self.attempt = 1
        self.pressed_notes.clear()
        self.captured_notes.clear()
        self.revealed_notes.clear()
        self.revealed_answer = False
        self.accepting_answer = False
        self.exercise = choose_exercise(
            self.patterns,
            self.args.chords,
            self.root_low,
            self.root_high,
            self.rng,
        )
        self.answer_var.set("")
        self._set_status("Listen")
        self._update_score()
        self._paint_keys()
        self._play_current()
        drain_pending(self.midi_input)
        self.accepting_answer = True
        self._set_status("Play your answer")

    def _replay(self) -> None:
        if self.exercise is None:
            return
        self._play_current()
        drain_pending(self.midi_input)

    def _show_answer(self) -> None:
        if self.exercise is None:
            return
        self.revealed_answer = True
        self.revealed_notes = set(self.exercise.notes)
        self.answer_var.set(self.exercise.prompt)
        self._paint_keys()

    def _play_current(self) -> None:
        if self.exercise is None:
            return
        notes = list(self.exercise.notes)
        for note in notes:
            self.midi_output.send(
                _note_message("note_on", note, self.args.velocity, self.output_channel)
            )
        self.root.after(
            int(self.args.duration * 1000),
            lambda: self._stop_notes(notes),
        )

    def _stop_notes(self, notes: list[int]) -> None:
        for note in notes:
            self.midi_output.send(_note_message("note_off", note, 0, self.output_channel))

    def _poll_midi(self) -> None:
        for message in self.midi_input.iter_pending():
            if self.input_channel is not None and getattr(message, "channel", None) != self.input_channel:
                continue
            if message.type == "note_on" and message.velocity > 0:
                if self.after_judge_id is not None:
                    self.root.after_cancel(self.after_judge_id)
                    self.after_judge_id = None
                self.pressed_notes.add(message.note)
                if self.accepting_answer:
                    self.captured_notes.append(message.note)
                self._paint_keys()
            elif message.type in {"note_off", "note_on"}:
                self.pressed_notes.discard(message.note)
                self._paint_keys()
                if self.accepting_answer and self.captured_notes and not self.pressed_notes:
                    if self.after_judge_id is not None:
                        self.root.after_cancel(self.after_judge_id)
                    self.after_judge_id = self.root.after(
                        int(self.args.quiet_after * 1000),
                        self._judge_current_answer,
                    )

        self.root.after(12, self._poll_midi)

    def _judge_current_answer(self) -> None:
        if self.exercise is None:
            return
        self.after_judge_id = None
        result = judge_answer(self.exercise.notes, tuple(self.captured_notes))
        if result.correct:
            self.accepting_answer = False
            self.completed += 1
            if self.attempt == 1 and not self.revealed_answer:
                self.first_try_correct += 1
            self._show_answer()
            self._set_status("Correct")
            self._update_score()
            self.after_next_id = self.root.after(int(self.args.next_delay * 1000), self._new_round)
            return

        self.attempt += 1
        self.captured_notes.clear()
        self._set_status("Not quite. Try the same chord again.")

    def _set_status(self, text: str) -> None:
        if self.args.forever:
            self.status_var.set(f"Round {self.round_number} · {text}")
        else:
            self.status_var.set(f"Round {self.round_number}/{self.args.rounds} · {text}")

    def _update_score(self) -> None:
        self.score_var.set(
            f"Completed {self.completed} · First-try correct {self.first_try_correct}/{max(self.completed, 1)}"
        )

    def _draw_keyboard(self) -> None:
        self.canvas.delete("all")
        self.keys.clear()

        width = max(self.canvas.winfo_width(), 300)
        height = max(self.canvas.winfo_height(), 180)
        margin_x = 16
        margin_y = 16
        white_notes = [note for note in range(self.keyboard_low, self.keyboard_high + 1) if note % 12 in WHITE_PCS]
        if not white_notes:
            return

        self.white_key_width = max(12, int((width - margin_x * 2) / len(white_notes)))
        self.key_height = height - margin_y * 2
        white_height = self.key_height
        black_height = int(white_height * 0.62)
        white_x: dict[int, int] = {}

        x = margin_x
        for note in white_notes:
            white_x[note] = x
            rect = self.canvas.create_rectangle(
                x,
                margin_y,
                x + self.white_key_width,
                margin_y + white_height,
                fill="#fffdf8",
                outline="#b9b3a7",
                width=1,
            )
            label = self.canvas.create_text(
                x + self.white_key_width / 2,
                margin_y + white_height - 18,
                text=_short_label(note),
                fill="#8a8174",
                font=("Helvetica", 10),
            )
            self.keys[note] = KeyGeometry(note, rect, label, False)
            x += self.white_key_width

        for note in range(self.keyboard_low, self.keyboard_high + 1):
            if note % 12 not in BLACK_PCS:
                continue
            prev_white = _previous_white(note)
            if prev_white not in white_x:
                continue
            black_width = max(8, int(self.white_key_width * 0.62))
            x0 = white_x[prev_white] + self.white_key_width - black_width // 2
            rect = self.canvas.create_rectangle(
                x0,
                margin_y,
                x0 + black_width,
                margin_y + black_height,
                fill="#24211d",
                outline="#16130f",
                width=1,
            )
            self.keys[note] = KeyGeometry(note, rect, None, True)

        self._paint_keys()

    def _paint_keys(self) -> None:
        answer_pcs = {note % 12 for note in self.revealed_notes}
        pressed_pcs = {note % 12 for note in self.pressed_notes}
        for note, key in self.keys.items():
            fill = "#24211d" if key.is_black else "#fffdf8"
            outline = "#16130f" if key.is_black else "#b9b3a7"
            if note % 12 in answer_pcs:
                fill = "#47c281" if key.is_black else "#a9e8c5"
                outline = "#248b59"
            if note % 12 in pressed_pcs:
                fill = "#f2b84b" if key.is_black else "#ffd98a"
                outline = "#b67318"
            self.canvas.itemconfigure(key.rect_id, fill=fill, outline=outline)


def run_gui(args, patterns: dict[str, ChordPattern]) -> int:
    try:
        app = EarTrainingApp(args, patterns)
    except Exception as exc:
        messagebox.showerror("Ear Training", str(exc))
        return 1
    app.run()
    return 0


def _note_message(message_type: str, note: int, velocity: int, channel: int):
    import mido

    return mido.Message(message_type, note=note, velocity=velocity, channel=channel)


def _previous_white(note: int) -> int:
    current = note - 1
    while current >= 0:
        if current % 12 in WHITE_PCS:
            return current
        current -= 1
    return note


def _short_label(note: int) -> str:
    name = midi_to_note_name(note)
    return name if name.startswith("C") else ""

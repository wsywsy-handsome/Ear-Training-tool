from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import random
import tkinter as tk
from dataclasses import dataclass
from tkinter import messagebox, ttk

import yaml

from ear_training.config import ChordPattern
from ear_training.midi_io import drain_pending, open_input, open_output, panic
from ear_training.music import (
    Exercise,
    PC_TO_NAME,
    choose_exercise,
    judge_answer,
    midi_to_note_name,
    parse_root_range,
)


WHITE_PCS = {0, 2, 4, 5, 7, 9, 11}
BLACK_PCS = {1, 3, 6, 8, 10}
GROUP_LABELS = {
    "triads": "三和弦",
    "suspended": "挂留和弦",
    "sevenths": "七和弦",
    "ninths": "九和弦",
    "custom": "自定义",
}


@dataclass(frozen=True)
class KeyGeometry:
    note: int
    rect_id: int
    text_id: int | None
    is_black: bool


@dataclass
class RoundRecord:
    round_number: int
    chord_name: str
    chord_label: str
    group: str
    root_pc: int
    attempts: int = 1
    manual_revealed: bool = False
    completed: bool = False

    @property
    def root_name(self) -> str:
        return PC_TO_NAME[self.root_pc]

    @property
    def first_try_correct(self) -> bool:
        return self.completed and self.attempts == 1 and not self.manual_revealed

    @property
    def weak(self) -> bool:
        return self.completed and (not self.first_try_correct or self.manual_revealed)


class EarTrainingApp:
    def __init__(self, args, patterns: dict[str, ChordPattern]) -> None:
        self.args = args
        self.patterns = patterns
        self.root_low, self.root_high = parse_root_range(args.root_range)
        self.keyboard_low, self.keyboard_high = parse_root_range(args.keyboard_range)
        self.rng = random.Random(args.seed)
        self.output_channel = args.output_channel - 1
        self.input_channel = args.input_channel - 1 if args.input_channel is not None else None
        self.settings_path = Path(args.settings)
        self.grouped_patterns = _group_patterns(patterns)
        self.selected_chords = self._load_initial_selection()
        self._save_settings()

        self.midi_input = open_input(args.input)
        self.midi_output = open_output(args.output)

        self.root = tk.Tk()
        self.root.title("Ear Training")
        self.root.geometry("1240x500")
        self.root.minsize(860, 420)
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
        self.ended = False
        self.after_next_id: str | None = None
        self.after_judge_id: str | None = None
        self.current_record: RoundRecord | None = None
        self.records: list[RoundRecord] = []

        self.keys: dict[int, KeyGeometry] = {}
        self.group_vars: dict[str, tk.BooleanVar] = {}
        self.chord_vars: dict[str, tk.BooleanVar] = {}
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
        self.root.columnconfigure(1, weight=0)
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
        ttk.Button(controls, text="显示答案", command=self._show_answer).grid(row=0, column=1, padx=(0, 8))
        ttk.Button(controls, text="结束训练", command=self._end_training).grid(row=0, column=2)

        self.canvas = tk.Canvas(self.root, bg="#f4f1eb", highlightthickness=0)
        self.canvas.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0, 14))
        self.canvas.bind("<Configure>", lambda _event: self._draw_keyboard())

        self._build_chord_selector()

    def _build_chord_selector(self) -> None:
        sidebar = ttk.Frame(self.root, padding=(0, 12, 14, 14))
        sidebar.grid(row=0, column=1, rowspan=2, sticky="ns")
        sidebar.rowconfigure(1, weight=1)
        sidebar.columnconfigure(0, weight=1)

        title = ttk.Label(sidebar, text="练习和弦", font=("Helvetica", 14, "bold"))
        title.grid(row=0, column=0, sticky="w", pady=(0, 8))

        scroll_canvas = tk.Canvas(sidebar, width=230, highlightthickness=0)
        scrollbar = ttk.Scrollbar(sidebar, orient="vertical", command=scroll_canvas.yview)
        scroll_canvas.configure(yscrollcommand=scrollbar.set)
        scroll_canvas.grid(row=1, column=0, sticky="ns")
        scrollbar.grid(row=1, column=1, sticky="ns")

        content = ttk.Frame(scroll_canvas)
        window_id = scroll_canvas.create_window((0, 0), window=content, anchor="nw")

        def update_scroll_region(_event=None) -> None:
            scroll_canvas.configure(scrollregion=scroll_canvas.bbox("all"))

        def sync_content_width(event) -> None:
            scroll_canvas.itemconfigure(window_id, width=event.width)

        def bind_mousewheel(_event) -> None:
            scroll_canvas.bind_all("<MouseWheel>", on_mousewheel)
            scroll_canvas.bind_all("<Button-4>", on_mousewheel)
            scroll_canvas.bind_all("<Button-5>", on_mousewheel)

        def unbind_mousewheel(_event) -> None:
            scroll_canvas.unbind_all("<MouseWheel>")
            scroll_canvas.unbind_all("<Button-4>")
            scroll_canvas.unbind_all("<Button-5>")

        def on_mousewheel(event) -> None:
            if getattr(event, "num", None) == 4:
                scroll_canvas.yview_scroll(-1, "units")
            elif getattr(event, "num", None) == 5:
                scroll_canvas.yview_scroll(1, "units")
            else:
                scroll_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        content.bind("<Configure>", update_scroll_region)
        scroll_canvas.bind("<Configure>", sync_content_width)
        scroll_canvas.bind("<Enter>", bind_mousewheel)
        scroll_canvas.bind("<Leave>", unbind_mousewheel)
        content.bind("<Enter>", bind_mousewheel)
        content.bind("<Leave>", unbind_mousewheel)

        row = 0
        for group, patterns in self.grouped_patterns.items():
            frame = ttk.LabelFrame(content, text=_group_label(group), padding=(10, 8))
            frame.grid(row=row, column=0, sticky="ew", pady=(0, 8))
            frame.columnconfigure(0, weight=1)
            row += 1

            group_var = tk.BooleanVar(value=all(pattern.name in self.selected_chords for pattern in patterns))
            self.group_vars[group] = group_var
            ttk.Checkbutton(
                frame,
                text="全选",
                variable=group_var,
                command=lambda group_name=group: self._toggle_group(group_name),
            ).grid(row=0, column=0, sticky="w")

            for index, pattern in enumerate(patterns, 1):
                var = tk.BooleanVar(value=pattern.name in self.selected_chords)
                self.chord_vars[pattern.name] = var
                ttk.Checkbutton(
                    frame,
                    text=f"{pattern.label}",
                    variable=var,
                    command=self._selection_changed,
                ).grid(row=index, column=0, sticky="w")

    def _new_round(self) -> None:
        if self.ended:
            return
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
        selected_chords = self._selected_chord_names()
        if not selected_chords:
            self.exercise = None
            self.accepting_answer = False
            self.answer_var.set("")
            self._set_status("Select at least one chord")
            self._paint_keys()
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
            selected_chords,
            self.root_low,
            self.root_high,
            self.rng,
        )
        self.current_record = RoundRecord(
            round_number=self.round_number,
            chord_name=self.exercise.pattern.name,
            chord_label=self.exercise.pattern.label,
            group=self.exercise.pattern.group,
            root_pc=self.exercise.root % 12,
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

    def _show_answer(self, manual: bool = True) -> None:
        if self.exercise is None:
            return
        if manual and self.current_record is not None and not self.current_record.completed:
            self.current_record.manual_revealed = True
        self.revealed_answer = True
        self.revealed_notes = set(self.exercise.notes)
        self.answer_var.set(self.exercise.prompt)
        self._paint_keys()

    def _end_training(self) -> None:
        self.ended = True
        self.accepting_answer = False
        if self.after_next_id is not None:
            self.root.after_cancel(self.after_next_id)
            self.after_next_id = None
        if self.after_judge_id is not None:
            self.root.after_cancel(self.after_judge_id)
            self.after_judge_id = None
        panic(self.midi_output, channel=self.output_channel)
        self._set_status("Training ended")
        self._show_report()

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
            self._finish_current_record()
            self._show_answer(manual=False)
            self._set_status("Correct")
            self._update_score()
            self.after_next_id = self.root.after(int(self.args.next_delay * 1000), self._new_round)
            return

        self.attempt += 1
        self.captured_notes.clear()
        self._set_status("Not quite. Try the same chord again.")

    def _finish_current_record(self) -> None:
        if self.current_record is None:
            return
        self.current_record.attempts = self.attempt
        self.current_record.completed = True
        self.records.append(self.current_record)
        self.completed += 1
        if self.current_record.first_try_correct:
            self.first_try_correct += 1

    def _show_report(self) -> None:
        report = tk.Toplevel(self.root)
        report.title("训练报告")
        report.geometry("780x620")
        report.minsize(640, 420)
        report.columnconfigure(0, weight=1)
        report.rowconfigure(0, weight=1)

        text = tk.Text(report, wrap="word", padx=16, pady=14)
        scrollbar = ttk.Scrollbar(report, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scrollbar.set)
        text.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        text.insert("1.0", self._build_report_text())
        text.configure(state="disabled")

        buttons = ttk.Frame(report, padding=(12, 8))
        buttons.grid(row=1, column=0, columnspan=2, sticky="e")
        ttk.Button(buttons, text="关闭报告", command=report.destroy).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(buttons, text="退出程序", command=self.close).grid(row=0, column=1)

    def _build_report_text(self) -> str:
        completed = [record for record in self.records if record.completed]
        if not completed:
            return "训练报告\n\n还没有完成任何题目。完成至少一题后再结束训练，就能生成薄弱点分析。"

        first_try = sum(1 for record in completed if record.first_try_correct)
        not_first_try = len(completed) - first_try
        revealed = sum(1 for record in completed if record.manual_revealed)
        weak = sum(1 for record in completed if record.weak)
        first_try_rate = first_try / len(completed)

        lines = [
            "训练报告",
            "",
            "判定说明：薄弱题 = 没有首次答对，或本题中手动点击过“显示答案”。",
            "",
            "总体",
            f"  完成题数：{len(completed)}",
            f"  首次答对：{first_try} ({first_try_rate:.0%})",
            f"  非首次答对：{not_first_try}",
            f"  手动显示答案：{revealed}",
            f"  薄弱题：{weak}",
            "",
        ]

        lines.extend(self._format_priority_section(completed))
        lines.extend(self._format_chord_type_section(completed))
        lines.extend(self._format_root_section(completed))
        return "\n".join(lines)

    def _format_priority_section(self, records: list[RoundRecord]) -> list[str]:
        chord_rows = _aggregate_records(
            records,
            key=lambda record: record.chord_name,
            label=lambda record: f"{record.chord_label} / {_group_label(record.group)}",
        )
        root_rows = _aggregate_records(
            records,
            key=lambda record: record.root_pc,
            label=lambda record: record.root_name,
        )
        chord_focus = _top_weak_labels(chord_rows)
        root_focus = _top_weak_labels(root_rows)
        lines = ["优先关注"]
        lines.append(f"  和弦类型：{', '.join(chord_focus) if chord_focus else '暂无明显薄弱项'}")
        lines.append(f"  根音：{', '.join(root_focus) if root_focus else '暂无明显薄弱项'}")
        lines.append("")
        return lines

    def _format_chord_type_section(self, records: list[RoundRecord]) -> list[str]:
        rows = _aggregate_records(
            records,
            key=lambda record: record.chord_name,
            label=lambda record: f"{record.chord_label} / {_group_label(record.group)}",
        )
        return _format_table("按和弦类型", rows)

    def _format_root_section(self, records: list[RoundRecord]) -> list[str]:
        rows = _aggregate_records(
            records,
            key=lambda record: record.root_pc,
            label=lambda record: record.root_name,
        )
        rows.sort(key=lambda row: row["key"])
        return _format_table("按根音", rows)

    def _set_status(self, text: str) -> None:
        if self.args.forever:
            self.status_var.set(f"Round {self.round_number} · {text}")
        else:
            self.status_var.set(f"Round {self.round_number}/{self.args.rounds} · {text}")

    def _update_score(self) -> None:
        self.score_var.set(
            f"Completed {self.completed} · First-try correct {self.first_try_correct}/{max(self.completed, 1)}"
        )

    def _toggle_group(self, group: str) -> None:
        selected = self.group_vars[group].get()
        for pattern in self.grouped_patterns[group]:
            self.chord_vars[pattern.name].set(selected)
        self._selection_changed()

    def _selection_changed(self) -> None:
        self.selected_chords = {
            name for name, var in self.chord_vars.items() if var.get() and name in self.patterns
        }
        self._sync_group_vars()
        self._save_settings()
        if not self.selected_chords:
            self._set_status("Select at least one chord")
        elif self.exercise is None:
            self._new_round()

    def _sync_group_vars(self) -> None:
        for group, patterns in self.grouped_patterns.items():
            self.group_vars[group].set(all(pattern.name in self.selected_chords for pattern in patterns))

    def _selected_chord_names(self) -> list[str]:
        return [name for name in self.patterns if name in self.selected_chords]

    def _load_initial_selection(self) -> set[str]:
        if self.args.chords:
            selected = {name for name in self.args.chords if name in self.patterns}
            return selected or set(self.patterns)

        saved = _load_saved_chords(self.settings_path)
        selected = {name for name in saved if name in self.patterns}
        return selected or set(self.patterns)

    def _save_settings(self) -> None:
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        data = {"selected_chords": self._selected_chord_names()}
        with self.settings_path.open("w", encoding="utf-8") as file:
            yaml.safe_dump(data, file, allow_unicode=True, sort_keys=False)

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


def _group_patterns(patterns: dict[str, ChordPattern]) -> dict[str, list[ChordPattern]]:
    grouped: dict[str, list[ChordPattern]] = defaultdict(list)
    for pattern in patterns.values():
        grouped[pattern.group].append(pattern)

    ordered: dict[str, list[ChordPattern]] = {}
    for group in ("triads", "suspended", "sevenths", "ninths"):
        if group in grouped:
            ordered[group] = grouped.pop(group)
    for group in sorted(grouped):
        ordered[group] = grouped[group]
    return ordered


def _group_label(group: str) -> str:
    return GROUP_LABELS.get(group, group.replace("_", " ").title())


def _load_saved_chords(path: Path) -> list[str]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as file:
        raw = yaml.safe_load(file) or {}
    selected = raw.get("selected_chords")
    if not isinstance(selected, list):
        return []
    return [str(name) for name in selected]


def _aggregate_records(records: list[RoundRecord], key, label) -> list[dict[str, object]]:
    rows: dict[object, dict[str, object]] = {}
    for record in records:
        row_key = key(record)
        if row_key not in rows:
            rows[row_key] = {
                "key": row_key,
                "label": label(record),
                "total": 0,
                "weak": 0,
                "not_first_try": 0,
                "revealed": 0,
            }
        row = rows[row_key]
        row["total"] = int(row["total"]) + 1
        if record.weak:
            row["weak"] = int(row["weak"]) + 1
        if not record.first_try_correct:
            row["not_first_try"] = int(row["not_first_try"]) + 1
        if record.manual_revealed:
            row["revealed"] = int(row["revealed"]) + 1

    result = list(rows.values())
    result.sort(
        key=lambda row: (
            -int(row["weak"]),
            -(int(row["weak"]) / max(int(row["total"]), 1)),
            str(row["label"]),
        )
    )
    return result


def _top_weak_labels(rows: list[dict[str, object]], limit: int = 3) -> list[str]:
    labels: list[str] = []
    for row in rows:
        weak = int(row["weak"])
        total = int(row["total"])
        if weak <= 0:
            continue
        labels.append(f"{row['label']} ({weak}/{total})")
        if len(labels) >= limit:
            break
    return labels


def _format_table(title: str, rows: list[dict[str, object]]) -> list[str]:
    lines = [
        title,
        "  项目                         总题  薄弱  非首次  看答案  薄弱率",
        "  -------------------------------------------------------------",
    ]
    for row in rows:
        total = int(row["total"])
        weak = int(row["weak"])
        not_first_try = int(row["not_first_try"])
        revealed = int(row["revealed"])
        weak_rate = weak / max(total, 1)
        label = str(row["label"])[:26]
        lines.append(
            f"  {label:<26} {total:>4}  {weak:>4}  {not_first_try:>6}  {revealed:>6}  {weak_rate:>6.0%}"
        )
    lines.append("")
    return lines

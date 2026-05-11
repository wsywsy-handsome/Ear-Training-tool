from collections import Counter
import random
import unittest

from ear_training.config import ChordPattern
from ear_training.music import (
    choose_exercise,
    judge_answer,
    midi_to_note_name,
    parse_note_name,
    parse_root_range,
)


class MusicTests(unittest.TestCase):
    def test_parse_note_name_middle_c(self) -> None:
        self.assertEqual(parse_note_name("C4"), 60)
        self.assertEqual(parse_note_name("Bb3"), 58)
        self.assertEqual(midi_to_note_name(61), "C#4")

    def test_parse_root_range(self) -> None:
        self.assertEqual(parse_root_range("C3:C4"), (48, 60))
        self.assertEqual(parse_root_range("D4"), (62, 62))

    def test_judge_answer_ignores_octave_and_order(self) -> None:
        result = judge_answer((60, 64, 67), (76, 72, 79, 84))
        self.assertTrue(result.correct)
        self.assertEqual(result.expected, ("C", "E", "G"))

    def test_judge_answer_reports_missing_and_extra(self) -> None:
        result = judge_answer((60, 64, 67), (60, 65, 67))
        self.assertFalse(result.correct)
        self.assertEqual(result.missing, ("E",))
        self.assertEqual(result.extra, ("F",))

    def test_choose_exercise_respects_midi_high_limit(self) -> None:
        patterns = {"wide": ChordPattern("wide", "Wide", (0, 4, 14))}
        exercise = choose_exercise(patterns, ["wide"], 100, 127, random.Random(0))
        self.assertLessEqual(max(exercise.notes), 127)
        self.assertEqual(exercise.pitch_classes, Counter(note % 12 for note in exercise.notes))


if __name__ == "__main__":
    unittest.main()

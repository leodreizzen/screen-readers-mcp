# Unit tests for adapters/nvda_live_speech_source.py: capture, and what became of each utterance.
# Copyright (C) 2026 Marlon Brandao de Sousa. GPL-2. See COPYING.txt.

from __future__ import annotations

import weakref
from collections.abc import Iterator
from typing import Any

import pytest
from fakes.clock import FakeClock
from support import nvda_stubs

nvda_stubs.install()

from nvdaMcpBridge import protocol
from nvdaMcpBridge.adapters.nvda_live_speech_source import NvdaLiveSpeechSource
from nvdaMcpBridge.domain.entities.speech_buffer import SpeechBuffer


@pytest.fixture(autouse=True)
def clean_extension_points() -> Iterator[None]:
	"""No registration outlives its test; NVDA's real points are process-wide."""
	yield
	nvda_stubs.reset()


class Live:
	"""Plays NVDA's part: speak() filters, the manager queues, the synth runs the callbacks."""

	def __init__(self, clock: FakeClock) -> None:
		self.buffer = SpeechBuffer(clock)
		self.source = NvdaLiveSpeechSource()
		self.source.start(self.buffer, lambda: 0)

	def speak(self, sequence: list[Any]) -> list[Any]:
		"""Returns what reached the manager, so a test can run its callbacks as the synth would."""
		filtered: Any = sequence
		for handler in nvda_stubs.filter_speechSequence.handlers:
			filtered = handler(filtered)
		for handler in nvda_stubs.pre_speechQueued.handlers:
			handler(speechSequence=filtered, priority=None)
		return list(filtered)

	def cancel(self) -> None:
		for handler in nvda_stubs.speechCanceled.handlers:
			handler()

	def fate(self, index: int) -> tuple[protocol.SpeechFate, bool]:
		return self.buffer.fate_at(index), self.buffer.started_at(index)


def callbacks(queued: list[Any]) -> list[Any]:
	return [c for c in queued if isinstance(c, nvda_stubs.StubCallbackCommand)]


def test_the_words_are_captured_unchanged(clock: FakeClock) -> None:
	live = Live(clock)
	live.speak(["Banco de pruebas", "documento"])
	assert [e[0] for e in live.buffer.entries_since(1)[0]] == ["Banco de pruebas documento"]


def test_an_utterance_is_pending_until_the_synth_reports(clock: FakeClock) -> None:
	live = Live(clock)
	live.speak(["words"])
	assert live.fate(1) == (protocol.SpeechFate.PENDING, False)


def test_reaching_both_marks_is_completed(clock: FakeClock) -> None:
	live = Live(clock)
	start, end = callbacks(live.speak(["words"]))
	start.run()
	end.run()
	assert live.fate(1) == (protocol.SpeechFate.COMPLETED, True)


def test_a_cancel_after_it_started_is_cancelled_and_started(clock: FakeClock) -> None:
	"""The S1 case: the long label began to sound and a keystroke cut it."""
	live = Live(clock)
	start, _end = callbacks(live.speak(["a very long label"]))
	start.run()
	live.cancel()
	assert live.fate(1) == (protocol.SpeechFate.CANCELLED, True)


def test_a_cancel_before_it_started_is_cancelled_and_never_sounded(clock: FakeClock) -> None:
	live = Live(clock)
	live.speak(["queued behind something"])
	live.cancel()
	assert live.fate(1) == (protocol.SpeechFate.CANCELLED, False)


def test_a_cancel_leaves_what_already_completed_alone(clock: FakeClock) -> None:
	live = Live(clock)
	first_start, first_end = callbacks(live.speak(["first"]))
	first_start.run()
	first_end.run()
	second_start, _ = callbacks(live.speak(["second"]))
	second_start.run()
	live.cancel()
	assert live.fate(1) == (protocol.SpeechFate.COMPLETED, True)
	assert live.fate(2) == (protocol.SpeechFate.CANCELLED, True)


def test_speech_queued_after_a_cancel_is_not_touched_by_it(clock: FakeClock) -> None:
	"""The S2 control: a later utterance queued behind an earlier one is not a cancellation."""
	live = Live(clock)
	live.speak(["first"])
	live.cancel()
	start, end = callbacks(live.speak(["second"]))
	start.run()
	end.run()
	assert live.fate(1) == (protocol.SpeechFate.CANCELLED, False)
	assert live.fate(2) == (protocol.SpeechFate.COMPLETED, True)


def test_queueing_behind_another_utterance_is_not_a_cancellation(clock: FakeClock) -> None:
	live = Live(clock)
	first = callbacks(live.speak(["a long polite announcement"]))
	second = callbacks(live.speak(["an alert"]))
	for mark in (*first, *second):
		mark.run()
	assert live.fate(1) == (protocol.SpeechFate.COMPLETED, True)
	assert live.fate(2) == (protocol.SpeechFate.COMPLETED, True)


def test_a_sequence_without_words_is_not_bracketed(clock: FakeClock) -> None:
	"""A text-free utterance may report no index, so its marks could never fire."""
	live = Live(clock)
	queued = live.speak([nvda_stubs.StubBeepCommand()])
	assert callbacks(queued) == []


def test_speech_queued_without_passing_the_filter_is_unknown(clock: FakeClock) -> None:
	"""Nothing to resolve it, so it must not be left pending forever."""
	live = Live(clock)
	for handler in nvda_stubs.pre_speechQueued.handlers:
		handler(speechSequence=["from elsewhere"], priority=None)
	assert live.fate(1) == (protocol.SpeechFate.UNKNOWN, False)


def test_stop_unregisters_every_point(clock: FakeClock) -> None:
	live = Live(clock)
	live.source.stop()
	assert nvda_stubs.filter_speechSequence.handlers == []
	assert nvda_stubs.pre_speechQueued.handlers == []
	assert nvda_stubs.speechCanceled.handlers == []


def test_marks_arriving_after_stop_do_nothing(clock: FakeClock) -> None:
	live = Live(clock)
	start, end = callbacks(live.speak(["words"]))
	live.source.stop()
	start.run()
	end.run()
	assert live.fate(1) == (protocol.SpeechFate.PENDING, False)


def test_a_captured_callback_does_not_outlive_its_speech(clock: FakeClock) -> None:
	"""A say all line carries its reader in a callback; holding it keeps NVDA's say all running."""

	class Reader:
		def line_reached(self) -> None: ...

	reader = Reader()
	alive = weakref.ref(reader)
	live = Live(clock)
	live.speak([nvda_stubs.StubCallbackCommand(reader.line_reached, name="say-all:lineReached"), "a line"])
	del reader
	assert alive() is None

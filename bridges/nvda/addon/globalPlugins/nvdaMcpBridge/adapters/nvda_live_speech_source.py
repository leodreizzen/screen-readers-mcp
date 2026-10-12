# nvdaMcpBridge adapters -- NvdaLiveSpeechSource: live-mode speech capture.
# Copyright (C) 2026 Marlon Brandao de Sousa. GPL-2. See COPYING.txt.
# ROLE: adapter implementing SpeechSource for live mode from pre_speechQueued; the real synth keeps talking.
# BUILT BY: adapters/nvda_adapter_factory.py.
# Live mode has no exact finish signal, so the SpeechBuffer's elapsed-time heuristic decides "finished".
# NVDA holds handlers weakly, so this instance must outlive its registration.
# Capture happens at QUEUE time, so a captured utterance may never have sounded. Each one is therefore
# bracketed with two CallbackCommands, which the speech manager runs when the synth reaches them: the
# first says it started, the last that it completed. speechCanceled resolves whatever was still open
# as cancelled, because cancelling drops the pending callbacks with the rest of the queue.
# The filter and pre_speechQueued run in the same synchronous speak() call, so the tracker is handed
# from one to the other rather than found in the sequence: the manager may rewrite its commands.

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from speech.commands import CallbackCommand
from speech.extensions import filter_speechSequence, pre_speechQueued, speechCanceled

from .. import protocol
from ..domain.ports.speech_source import SpeechSource

if TYPE_CHECKING:
	from ..domain.entities.speech_buffer import SpeechBuffer


class _Tracker:
	"""One utterance's link between NVDA's callbacks and the buffer index its capture landed at.

	A callback can only fire after its utterance was queued, so ``index`` is set before either mark
	runs; ``None`` means the queue step never happened and the marks have nothing to resolve.
	"""

	__slots__ = ("index",)

	def __init__(self) -> None:
		self.index: int | None = None


def _has_words(sequence: Any) -> bool:
	"""A text-free utterance may report no index, so its callbacks would never fire."""
	return isinstance(sequence, (list, tuple)) and any(
		isinstance(c, str) and c.strip()
		for c in sequence  # pyright: ignore[reportUnknownVariableType]
	)


class NvdaLiveSpeechSource(SpeechSource):
	def __init__(self) -> None:
		self._buffer: SpeechBuffer | None = None
		self._log_position: Callable[[], int] = lambda: 0
		self._registered = False
		#: Set by the filter, consumed by the next pre_speechQueued of the same speak() call.
		self._handoff: _Tracker | None = None
		#: Queued and not yet resolved; speechCanceled cancels all of them.
		self._open: set[_Tracker] = set()

	def start(self, buffer: SpeechBuffer, log_position: Callable[[], int]) -> None:
		self._buffer = buffer
		self._log_position = log_position
		filter_speechSequence.register(self._bracket)
		pre_speechQueued.register(self._on_speech_queued)
		speechCanceled.register(self._on_speech_canceled)
		self._registered = True

	def stop(self) -> None:
		if self._registered:
			filter_speechSequence.unregister(self._bracket)
			pre_speechQueued.unregister(self._on_speech_queued)
			speechCanceled.unregister(self._on_speech_canceled)
			self._registered = False
		self._buffer = None
		self._handoff = None
		self._open.clear()

	def suspend(self) -> None:
		"""No-op in live mode: nothing was ever suppressed."""

	def resume(self) -> None:
		"""No-op in live mode: nothing was ever suppressed."""

	def stop_suppressing(self) -> None:
		"""No-op in live mode: nothing was ever suppressed."""

	def resume_suppressing(self) -> None:
		"""No-op in live mode: nothing was ever suppressed."""

	def is_suppressing(self) -> bool:
		return False

	def _bracket(self, speechSequence: Any) -> Any:
		"""Filter handler: returns the sequence with a start and an end mark; never suppresses."""
		self._handoff = None
		if self._buffer is None or not _has_words(speechSequence):
			return speechSequence
		tracker = _Tracker()
		self._handoff = tracker
		return [
			CallbackCommand(lambda: self._on_started(tracker), name="nvdaMcpBridge.started"),
			*speechSequence,
			CallbackCommand(lambda: self._on_completed(tracker), name="nvdaMcpBridge.completed"),
		]

	def _on_speech_queued(self, speechSequence: Any = None, **kwargs: Any) -> None:
		buffer = self._buffer
		tracker, self._handoff = self._handoff, None
		if buffer is None or not speechSequence:
			return
		if tracker is None:
			buffer.append(speechSequence, self._log_position())
			return
		tracker.index = buffer.append(speechSequence, self._log_position(), protocol.SpeechFate.PENDING)
		self._open.add(tracker)

	def _on_started(self, tracker: _Tracker) -> None:
		buffer = self._buffer
		if buffer is not None and tracker.index is not None:
			buffer.mark_started(tracker.index)

	def _on_completed(self, tracker: _Tracker) -> None:
		self._open.discard(tracker)
		buffer = self._buffer
		if buffer is not None and tracker.index is not None:
			buffer.mark_completed(tracker.index)

	def _on_speech_canceled(self, **kwargs: Any) -> None:
		buffer = self._buffer
		closing, self._open = self._open, set()
		if buffer is None:
			return
		for tracker in closing:
			if tracker.index is not None:
				buffer.mark_cancelled(tracker.index)

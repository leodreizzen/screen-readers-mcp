// ROLE: entity, one thing the reader said, as it travels on the wire.
// `index` is assigned by the bridge, never taken from the capture extension; see Utterance.swift.
// `logPosition` defaults to 0, because VoiceOver has no log to position into.
// `emittedAt` is a wall-clock `YYYY-MM-DD HH:MM:SS.mmm`, not ISO 8601, as in the session transcript.
// `fate` defaults to `.unknown`: this bridge does not observe what became of an utterance after capture.

public struct SpeechEntry: Codable, Equatable, Sendable {
	public var text: String
	public var index: Int
	public var logPosition: Int
	public var emittedAt: String = ""
	public var fate: SpeechFate = .unknown
	public var startedSpeaking: Bool = false

	public init(
		text: String, index: Int, logPosition: Int, emittedAt: String = "",
		fate: SpeechFate = .unknown, startedSpeaking: Bool = false
	) {
		self.text = text
		self.index = index
		self.logPosition = logPosition
		self.emittedAt = emittedAt
		self.fate = fate
		self.startedSpeaking = startedSpeaking
	}

	public init(from decoder: any Decoder) throws {
		let box = try decoder.container(keyedBy: CodingKeys.self)
		text = try box.decode(String.self, forKey: .text)
		index = try box.decode(Int.self, forKey: .index)
		logPosition = try box.decode(Int.self, forKey: .logPosition)
		emittedAt = try box.decode(String.self, forKey: .emittedAt, orDefault: emittedAt)
		fate = try box.decode(SpeechFate.self, forKey: .fate, orDefault: fate)
		startedSpeaking = try box.decode(Bool.self, forKey: .startedSpeaking, orDefault: startedSpeaking)
	}
}

/// What became of an utterance after the reader queued it; see protocol.py.
public enum SpeechFate: String, Codable, CaseIterable, Sendable {
	case completed
	case cancelled
	case pending
	case unknown
}

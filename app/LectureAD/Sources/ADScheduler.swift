import AVFoundation
import Combine

/// Transport surface shared by both players so menu commands (AppModel) can drive
/// whichever one is active.
@MainActor
protocol TransportControllable: Playable {
    var currentTime: Double { get }
    var isMuted: Bool { get }
    var ad: ADScheduler { get }
    func skip(_ delta: Double)
    func seek(to t: Double)
    func toggleMute()
}

/// Shared extended-AD engine for both players: owns the cue -> .ext.wav bookkeeping and
/// realises the user's "when should the AD talk" choice (§8):
/// - auto:      pause the video and speak every description as its moment arrives
///              (the original behaviour).
/// - onDemand:  descriptions never auto-play; the latest one is held as `pendingCue`
///              (on-screen badge + soft VoiceOver ping) until the user asks for it.
/// - off:       descriptions are consumed silently; rewinding re-arms them.
@MainActor
final class ADScheduler: ObservableObject {
    enum Mode: String, CaseIterable, Identifiable {
        case auto, onDemand, off
        var id: String { rawValue }
        var label: String {
            switch self {
            case .auto: return "Automatic"
            case .onDemand: return "On-Demand"
            case .off: return "Off"
            }
        }
    }

    @Published var mode: Mode = .auto
    @Published private(set) var isSpeaking = false
    @Published private(set) var activeCue: Cue?
    @Published private(set) var pendingCue: Cue?

    var canReplay: Bool { lastPlayedIndex != nil }
    /// Every registered extended cue — the players' find-in-lecture search corpus (⌘F).
    var allCues: [Cue] { entries.map { $0.cue } }

    // Wired by the owning player.
    var pauseVideo: () -> Void = {}
    var resumeVideo: () -> Void = {}
    var isVideoPlaying: () -> Bool = { false }
    var announce: (String) -> Void = { _ in }

    private struct Entry {
        let cue: Cue
        let duration: Double
        let offset: Double  // start offset of this clip within its concatenated .ext.wav
        let playerKey: Int
    }

    private var entries: [Entry] = []
    private var players: [Int: AVAudioPlayer] = [:]
    private var activePlayer: AVAudioPlayer?
    private var fired = Set<Int>()
    private var pendingIndex: Int?
    private var lastPlayedIndex: Int?
    private var finishWork: DispatchWorkItem?
    private var resumeAfter = false

    /// Register a batch of extended cues backed by one concatenated .ext.wav
    /// (clip offset = cumulative duration of the prior cues in the same file).
    func add(cues: [Cue], player: AVAudioPlayer?, forKey key: Int) {
        guard !cues.isEmpty else { return }
        var running = 0.0
        for cue in cues {
            entries.append(Entry(cue: cue, duration: cue.end - cue.start, offset: running,
                                 playerKey: key))
            running += cue.end - cue.start
        }
        if let player {
            player.prepareToPlay()
            players[key] = player
        }
    }

    /// Advance the scheduler. Call from the player's periodic tick.
    func tick(now: Double) {
        guard !isSpeaking else { return }
        let crossed = entries.indices.filter { !fired.contains($0) && now >= entries[$0].cue.start }
        guard let first = crossed.first, let last = crossed.last else { return }
        switch mode {
        case .auto:
            fired.insert(first)  // earliest first — the original one-at-a-time behaviour
            play(first)
        case .off:
            crossed.forEach { fired.insert($0) }
        case .onDemand:
            crossed.forEach { fired.insert($0) }
            pendingIndex = last  // the most recent moment wins; rewinding re-arms older ones
            pendingCue = entries[last].cue
            announce("Description available. Press D to hear it.")
        }
    }

    /// Seeking interrupts any speech and re-arms cues at/after the target so rewinding
    /// replays their descriptions (same policy the players had before).
    func handleSeek(to t: Double) {
        cancelCurrent()
        fired = Set(fired.filter { entries[$0].cue.start < t })
        pendingIndex = nil
        pendingCue = nil
    }

    /// Play the description the badge is offering (on-demand mode).
    func playPendingNow() {
        guard let i = pendingIndex else {
            announce("No description available right now.")
            return
        }
        pendingIndex = nil
        pendingCue = nil
        play(i)
    }

    /// Skip the description currently speaking; the video resumes immediately.
    func skipCurrent() {
        cancelCurrent()
    }

    /// Replay the most recently played description (survives seeks).
    func replayLast() {
        guard let i = lastPlayedIndex else { return }
        cancelCurrent()
        play(i)
    }

    /// Interrupt in-progress speech (e.g. the user seeked away).
    func cancelCurrent() {
        guard isSpeaking else { return }
        finishWork?.cancel()
        finish()
    }

    private func play(_ index: Int) {
        let e = entries[index]
        guard let ext = players[e.playerKey] else { return }
        lastPlayedIndex = index
        resumeAfter = isVideoPlaying()
        pauseVideo()  // pause the video for the description
        isSpeaking = true
        activeCue = e.cue
        activePlayer = ext
        ext.currentTime = e.offset
        ext.play()
        // Stop on the cue duration — it already includes the pipeline's 0.4 s padded tail,
        // which absorbs audio-start latency so the last words aren't clipped.
        let work = DispatchWorkItem { [weak self] in self?.finish() }
        finishWork = work
        DispatchQueue.main.asyncAfter(deadline: .now() + e.duration, execute: work)
    }

    /// Normal end of a description: stop the AD audio and resume the video if it was playing.
    private func finish() {
        finishWork = nil
        activePlayer?.stop()
        activePlayer = nil
        isSpeaking = false
        activeCue = nil
        if resumeAfter { resumeVideo() }
    }
}

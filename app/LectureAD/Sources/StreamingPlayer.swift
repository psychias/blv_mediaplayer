import AVFoundation
import Combine

/// Streaming player that stays fully seekable. Instead of a forward-only queue, it builds a
/// single growing AVMutableComposition on the GLOBAL timeline: each window appends its video
/// segment + enhanced audio at its real time, so you can scrub anywhere already prepared.
/// Each time the playhead enters a new window it grants one pacing credit, keeping the engine
/// only a couple of windows ahead (bounded lookahead) so the GPU stays free for smooth video.
/// Reads cached window artifacts only — never inference (§1, §12).
@MainActor
final class StreamingPlayer: ObservableObject {
    @Published private(set) var currentTime: Double = 0
    @Published private(set) var isPlaying = false
    @Published private(set) var isMuted = false
    @Published private(set) var isBuffering = false
    @Published private(set) var inExtendedDescription = false
    @Published private(set) var activeExtended: Cue?
    @Published private(set) var totalReady: Double = 0  // global seconds prepared so far

    let player = AVPlayer()
    private let videoURL: URL
    private let grantCredit: () -> Void
    private let composition = AVMutableComposition()
    private var videoTrack: AVMutableCompositionTrack?
    private var audioTrack: AVMutableCompositionTrack?

    private var windows: [StreamWindowInfo] = []
    private var captions: [Cue] = []
    private struct Ext { let cue: Cue; let dur: Double; let offset: Double; let window: Int }
    private var extEntries: [Ext] = []
    private var extPlayers: [Int: AVAudioPlayer] = [:]
    private var fired: Set<Int> = []
    private var enteredWindow = -1
    private var observer: Any?

    init(videoURL: URL, grantCredit: @escaping () -> Void) {
        self.videoURL = videoURL
        self.grantCredit = grantCredit
        videoTrack = composition.addMutableTrack(withMediaType: .video, preferredTrackID: kCMPersistentTrackID_Invalid)
        audioTrack = composition.addMutableTrack(withMediaType: .audio, preferredTrackID: kCMPersistentTrackID_Invalid)
        player.actionAtItemEnd = .pause  // hitting the end of the prepared range must NOT loop to 0
        let interval = CMTime(seconds: 0.2, preferredTimescale: 600)
        observer = player.addPeriodicTimeObserver(forInterval: interval, queue: .main) { [weak self] _ in
            Task { @MainActor in self?.tick() }
        }
        MediaRemote.shared.attach(self)  // hardware media keys (play/pause) control this player
    }

    deinit { if let o = observer { player.removeTimeObserver(o) } }

    /// Append a freshly-prepared window onto the global timeline.
    func addWindow(_ w: StreamWindowInfo) async {
        captions += VTT.parse(w.captionsURL).filter { $0.kind != .extended }
        let ext = VTT.parse(w.descriptionsURL).filter { $0.kind == .extended }
        if !ext.isEmpty {
            var running = 0.0
            for c in ext {
                extEntries.append(Ext(cue: c, dur: c.end - c.start, offset: running, window: w.index))
                running += (c.end - c.start)
            }
            if let url = w.extendedAudioURL { extPlayers[w.index] = try? AVAudioPlayer(contentsOf: url) }
        }

        let video = AVURLAsset(url: videoURL)
        let audio = AVURLAsset(url: w.audioURL)
        let at = CMTime(seconds: w.tStart, preferredTimescale: 600)
        do {
            if let vt = videoTrack, let src = try await video.loadTracks(withMediaType: .video).first {
                let range = CMTimeRange(start: at, end: CMTime(seconds: w.tEnd, preferredTimescale: 600))
                try vt.insertTimeRange(range, of: src, at: at)
            }
            if let aTrack = audioTrack, let src = try await audio.loadTracks(withMediaType: .audio).first {
                let dur = try await audio.load(.duration)
                try aTrack.insertTimeRange(CMTimeRange(start: .zero, duration: dur), of: src, at: at)
            }
        } catch { return }

        windows.append(w)
        totalReady = w.tEnd
        isBuffering = false
        refreshItem(startIfFirst: windows.count == 1)
    }

    /// Re-point the player at the grown composition, preserving the playhead.
    private func refreshItem(startIfFirst: Bool) {
        let t = player.currentItem == nil ? CMTime.zero : player.currentTime()
        let resume = startIfFirst || isPlaying
        let snapshot = composition.copy() as! AVComposition  // immutable snapshot
        player.replaceCurrentItem(with: AVPlayerItem(asset: snapshot))
        // Resume ONLY after the seek lands. Replacing the item resets the playhead to 0 and the
        // seek is async, so calling play() immediately can start from the beginning — which is
        // exactly what happens when a window arrives at/after the end of the prepared range.
        player.seek(to: t, toleranceBefore: .zero, toleranceAfter: .zero) { [weak self] _ in
            guard let self, resume else { return }
            self.play()
        }
    }

    // MARK: transport — full seek across the prepared range
    func playPause() { isPlaying ? pause() : play() }
    func play() { player.play(); isPlaying = true; MediaRemote.shared.update(isPlaying: true) }
    func pause() { player.pause(); isPlaying = false; MediaRemote.shared.update(isPlaying: false) }
    func seek(to t: Double) {
        let clamped = max(0, min(t, totalReady))
        // Re-arm any extended cues at/after the seek target so rewinding replays their AD.
        fired = Set(fired.filter { extEntries[$0].cue.start < clamped })
        player.seek(to: CMTime(seconds: clamped, preferredTimescale: 600))
    }
    func skip(_ delta: Double) { seek(to: currentTime + delta) }
    func toggleMute() { player.isMuted.toggle(); isMuted = player.isMuted }
    func setDucked(_ d: Bool) { player.volume = d ? 0.25 : 1.0 }

    func activeLecturer() -> Cue? { active(.lecturer) }
    func activeAD() -> Cue? { active(.ad) }
    private func active(_ k: CueKind) -> Cue? {
        captions.first { $0.kind == k && currentTime >= $0.start && currentTime < $0.end }
    }

    /// Every prepared cue with text, in time order — the find-in-lecture search corpus (⌘F).
    var searchCues: [Cue] { (captions + extEntries.map { $0.cue }).sorted { $0.start < $1.start } }

    private func tick() {
        currentTime = player.currentTime().seconds
        // Buffering if we've run into not-yet-prepared territory.
        isBuffering = isPlaying && currentTime >= totalReady - 0.1 && player.timeControlStatus != .playing

        // Grant a pacing credit when the playhead enters a new window (keeps lookahead bounded).
        if let idx = windows.firstIndex(where: { currentTime >= $0.tStart && currentTime < $0.tEnd }),
           idx > enteredWindow {
            enteredWindow = idx
            grantCredit()
        }

        guard !inExtendedDescription else { return }
        for (i, e) in extEntries.enumerated() where !fired.contains(i) && currentTime >= e.cue.start {
            fired.insert(i)
            if let p = extPlayers[e.window] { playExtended(p, e) }
            break
        }
    }

    private func playExtended(_ ext: AVAudioPlayer, _ e: Ext) {
        let wasPlaying = isPlaying
        pause()
        inExtendedDescription = true
        activeExtended = e.cue
        ext.currentTime = e.offset
        ext.play()
        DispatchQueue.main.asyncAfter(deadline: .now() + e.dur) { [weak self] in
            ext.stop()
            self?.inExtendedDescription = false
            self?.activeExtended = nil
            if wasPlaying { self?.play() }
        }
    }
}

extension StreamingPlayer: Playable {}

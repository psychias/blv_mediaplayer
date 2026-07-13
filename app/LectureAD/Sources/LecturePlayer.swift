import AVFoundation
import Combine

/// Plays the original video track with the cached enhanced-audio `.wav` (the original
/// audio is dropped), tracks the active caption cues, and realises extended AD (rung 0)
/// by pausing the video to play the matching segment of the bundled `.ext.wav`.
///
/// It consumes a finished cached artifact only — it never triggers inference (§1).
@MainActor
final class LecturePlayer: ObservableObject {
    @Published private(set) var currentTime: Double = 0
    @Published private(set) var isPlaying = false
    @Published private(set) var isMuted = false
    @Published private(set) var inExtendedDescription = false
    @Published private(set) var activeExtended: Cue?

    let player = AVPlayer()
    private let videoURL: URL
    private let audioURL: URL
    private let captions: [Cue]
    private let extendedCues: [Cue]
    private let extendedOffsets: [Double]  // start offset of each rung-0 clip in ext.wav
    private var extendedPlayer: AVAudioPlayer?
    private var firedExtended = Set<Int>()
    private var timeObserver: Any?

    init(videoURL: URL, artifacts: Artifacts, captions: [Cue], extended: [Cue]) {
        self.videoURL = videoURL
        self.audioURL = artifacts.audioURL
        self.captions = captions
        self.extendedCues = extended
        // ext.wav concatenates the rung-0 clips in cue order; offset = cumulative duration.
        var running = 0.0
        var offsets: [Double] = []
        for cue in extended { offsets.append(running); running += (cue.end - cue.start) }
        self.extendedOffsets = offsets

        if let url = artifacts.extendedAudioURL {
            extendedPlayer = try? AVAudioPlayer(contentsOf: url)
            extendedPlayer?.prepareToPlay()
        }
    }

    deinit { if let o = timeObserver { player.removeTimeObserver(o) } }

    /// Build the video+enhanced-audio composition with modern async asset loading, then
    /// start observing time and play. Call once from the view's `.task`.
    func start() async {
        let video = AVURLAsset(url: videoURL)
        let audio = AVURLAsset(url: audioURL)
        let composition = AVMutableComposition()
        do {
            if let vt = composition.addMutableTrack(withMediaType: .video, preferredTrackID: kCMPersistentTrackID_Invalid),
               let src = try await video.loadTracks(withMediaType: .video).first {
                try vt.insertTimeRange(CMTimeRange(start: .zero, duration: try await video.load(.duration)), of: src, at: .zero)
            }
            if let at = composition.addMutableTrack(withMediaType: .audio, preferredTrackID: kCMPersistentTrackID_Invalid),
               let src = try await audio.loadTracks(withMediaType: .audio).first {
                try at.insertTimeRange(CMTimeRange(start: .zero, duration: try await audio.load(.duration)), of: src, at: .zero)
            }
        } catch {
            return
        }
        player.replaceCurrentItem(with: AVPlayerItem(asset: composition))
        let interval = CMTime(seconds: 0.2, preferredTimescale: 600)
        timeObserver = player.addPeriodicTimeObserver(forInterval: interval, queue: .main) { [weak self] t in
            Task { @MainActor in self?.tick(t.seconds) }
        }
        MediaRemote.shared.attach(self)  // hardware media keys (play/pause) control this player
        play()
    }

    // MARK: transport (all standard, labelled in the UI)
    func playPause() { isPlaying ? pause() : play() }
    func play() { player.play(); isPlaying = true; MediaRemote.shared.update(isPlaying: true) }
    func pause() { player.pause(); isPlaying = false; MediaRemote.shared.update(isPlaying: false) }
    func seek(to seconds: Double) {
        let target = max(0, seconds)
        // Re-arm any extended cues at/after the seek target so rewinding replays their AD.
        firedExtended = Set(firedExtended.filter { extendedCues[$0].start < target })
        player.seek(to: CMTime(seconds: target, preferredTimescale: 600))
    }
    func skip(_ delta: Double) { seek(to: currentTime + delta) }
    func toggleMute() { player.isMuted.toggle(); isMuted = player.isMuted }

    func activeLecturer() -> Cue? { active(.lecturer) }
    func activeAD() -> Cue? { active(.ad) }
    private func active(_ kind: CueKind) -> Cue? {
        captions.first { $0.kind == kind && currentTime >= $0.start && currentTime < $0.end }
    }

    /// Every cue with text, in time order — the find-in-lecture search corpus (⌘F).
    var searchCues: [Cue] { (captions + extendedCues).sorted { $0.start < $1.start } }

    /// Briefly lower the lecture audio (e.g. while VoiceOver speaks) so they don't collide (§8).
    func setDucked(_ ducked: Bool) { player.volume = ducked ? 0.25 : 1.0 }

    private func tick(_ time: Double) {
        currentTime = time
        guard !inExtendedDescription else { return }
        for (i, cue) in extendedCues.enumerated() where !firedExtended.contains(i) {
            if time >= cue.start {
                firedExtended.insert(i)
                playExtended(index: i, cue: cue)
                break
            }
        }
    }

    private func playExtended(index: Int, cue: Cue) {
        guard let ext = extendedPlayer else { return }
        let wasPlaying = isPlaying
        pause()                              // pause the video for the extended description
        inExtendedDescription = true
        activeExtended = cue
        ext.currentTime = extendedOffsets[index]
        ext.play()
        let duration = cue.end - cue.start
        DispatchQueue.main.asyncAfter(deadline: .now() + duration) { [weak self] in
            ext.stop()
            self?.inExtendedDescription = false
            self?.activeExtended = nil
            if wasPlaying { self?.play() }    // resume
        }
    }
}

extension LecturePlayer: Playable {}

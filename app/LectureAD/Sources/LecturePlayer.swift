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

    let player = AVPlayer()
    let ad = ADScheduler()
    var inExtendedDescription: Bool { ad.isSpeaking }
    var activeExtended: Cue? { ad.activeCue }

    private let videoURL: URL
    private let audioURL: URL
    private let captions: [Cue]
    private var timeObserver: Any?
    private var adSub: AnyCancellable?
    private var started = false

    init(videoURL: URL, artifacts: Artifacts, captions: [Cue], extended: [Cue]) {
        self.videoURL = videoURL
        self.audioURL = artifacts.audioURL
        self.captions = captions
        ad.add(cues: extended,
               player: artifacts.extendedAudioURL.flatMap { try? AVAudioPlayer(contentsOf: $0) },
               forKey: 0)
        ad.pauseVideo = { [weak self] in self?.pause() }
        ad.resumeVideo = { [weak self] in self?.play() }
        ad.isVideoPlaying = { [weak self] in self?.isPlaying ?? false }
        adSub = ad.objectWillChange.sink { [weak self] _ in self?.objectWillChange.send() }
    }

    deinit { if let o = timeObserver { player.removeTimeObserver(o) } }

    /// Build the video+enhanced-audio composition with modern async asset loading, then
    /// start observing time and play. Idempotent — the view's `.task` may re-run.
    func start() async {
        guard !started else { return }
        started = true
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
        ad.handleSeek(to: target)  // interrupts speech; re-arms cues so rewinding replays AD
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
    var searchCues: [Cue] { (captions + ad.allCues).sorted { $0.start < $1.start } }

    /// Briefly lower the lecture audio (e.g. while VoiceOver speaks) so they don't collide (§8).
    func setDucked(_ ducked: Bool) { player.volume = ducked ? 0.25 : 1.0 }

    private func tick(_ time: Double) {
        currentTime = time
        ad.tick(now: time)
    }
}

extension LecturePlayer: TransportControllable {}

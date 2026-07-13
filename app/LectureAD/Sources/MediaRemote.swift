import MediaPlayer

/// Anything the media keys / remote commands can drive.
@MainActor
protocol Playable: AnyObject {
    var isPlaying: Bool { get }
    func play()
    func pause()
    func playPause()
}

/// Routes the hardware media keys (play/pause, etc.) and Control Center transport to the
/// active player via MPRemoteCommandCenter, and publishes Now Playing info so macOS knows
/// this app owns media playback (required for the keys to reach us).
@MainActor
final class MediaRemote {
    static let shared = MediaRemote()
    private weak var player: Playable?

    func attach(_ player: Playable) {
        self.player = player
        let c = MPRemoteCommandCenter.shared()
        for cmd in [c.playCommand, c.pauseCommand, c.togglePlayPauseCommand, c.stopCommand] {
            cmd.removeTarget(nil)
            cmd.isEnabled = true
        }
        c.togglePlayPauseCommand.addTarget { [weak self] _ in self?.player?.playPause(); return .success }
        c.playCommand.addTarget { [weak self] _ in self?.player?.play(); return .success }
        c.pauseCommand.addTarget { [weak self] _ in self?.player?.pause(); return .success }
        c.stopCommand.addTarget { [weak self] _ in self?.player?.pause(); return .success }
        MPNowPlayingInfoCenter.default().nowPlayingInfo = [
            MPMediaItemPropertyTitle: "Lecture",
            MPNowPlayingInfoPropertyPlaybackRate: 1.0,
        ]
        update(isPlaying: player.isPlaying)
    }

    func update(isPlaying: Bool) {
        MPNowPlayingInfoCenter.default().playbackState = isPlaying ? .playing : .paused
        var info = MPNowPlayingInfoCenter.default().nowPlayingInfo ?? [:]
        info[MPNowPlayingInfoPropertyPlaybackRate] = isPlaying ? 1.0 : 0.0
        MPNowPlayingInfoCenter.default().nowPlayingInfo = info
    }
}

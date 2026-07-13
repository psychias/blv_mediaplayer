import SwiftUI

/// Batch player: plays one finished cached artifact (video + enhanced audio + captions).
struct PlayerView: View {
    @StateObject private var player: LecturePlayer
    @EnvironmentObject private var settings: CaptionSettings
    @EnvironmentObject private var model: AppModel
    @State private var showSearch = false

    init(videoURL: URL, artifacts: Artifacts) {
        let captions = VTT.parse(artifacts.captionsURL)
        let extended = VTT.parse(artifacts.descriptionsURL)
        _player = StateObject(wrappedValue: LecturePlayer(
            videoURL: videoURL, artifacts: artifacts, captions: captions, extended: extended))
    }

    var body: some View {
        VStack(spacing: 0) {
            ZStack {
                PlayerLayerView(player: player.player, zoom: settings.videoZoom)
                CaptionsOverlay(lecturer: player.activeLecturer(), ad: player.activeAD(),
                                extended: player.activeExtended, inExtended: player.inExtendedDescription,
                                settings: settings)
            }
            TransportControls(
                isPlaying: player.isPlaying, isMuted: player.isMuted,
                currentTime: player.currentTime, duration: duration,
                onPlayPause: player.playPause, onSkip: player.skip, onSeek: player.seek(to:),
                onMute: player.toggleMute, onOpen: model.requestOpen,
                onSearch: { showSearch = true })
            CaptionControlBar(settings: settings) { d in
                settings.videoZoom = min(3.0, max(1.0, settings.videoZoom + d))
            }
        }
        .task { await player.start() }
        .sheet(isPresented: $showSearch) {
            SearchSheet(cues: player.searchCues) { player.seek(to: $0) }
        }
    }

    private var duration: Double {
        let d = player.player.currentItem?.duration.seconds ?? 0
        return d.isFinite ? d : 1
    }
}

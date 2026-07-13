import SwiftUI

/// Streaming player UI: starts on window 0 and keeps playing as windows append. Reuses the
/// shared caption overlay and transport so it matches the batch player.
struct StreamingPlayerView: View {
    @ObservedObject var player: StreamingPlayer
    @EnvironmentObject private var settings: CaptionSettings
    @EnvironmentObject private var model: AppModel
    @State private var showSearch = false

    var body: some View {
        VStack(spacing: 0) {
            ZStack {
                PlayerLayerView(player: player.player, zoom: settings.videoZoom)
                CaptionsOverlay(lecturer: player.activeLecturer(), ad: player.activeAD(),
                                extended: player.activeExtended, inExtended: player.inExtendedDescription,
                                settings: settings)
                if player.isBuffering {
                    Text("Preparing next part…")
                        .padding(10).background(.black.opacity(0.7))
                        .foregroundStyle(.white).clipShape(Capsule())
                        .accessibilityLabel("Preparing the next part of the lecture")
                }
            }
            TransportControls(
                isPlaying: player.isPlaying, isMuted: player.isMuted,
                currentTime: player.currentTime, duration: player.totalReady,
                onPlayPause: player.playPause, onSkip: player.skip, onSeek: player.seek(to:),
                onMute: player.toggleMute, onOpen: model.requestOpen,
                onSearch: { showSearch = true })
            CaptionControlBar(settings: settings) { d in
                settings.videoZoom = min(3.0, max(1.0, settings.videoZoom + d))
            }
        }
        .sheet(isPresented: $showSearch) {
            SearchSheet(cues: player.searchCues) { player.seek(to: $0) }
        }
    }
}

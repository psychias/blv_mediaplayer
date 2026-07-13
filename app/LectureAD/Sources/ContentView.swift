import SwiftUI
import UniformTypeIdentifiers

struct ContentView: View {
    @EnvironmentObject var model: AppModel

    var body: some View {
        Group {
            switch model.phase {
            case .idle:
                ChooseView()
            case let .preparing(stage, pct, label):
                PrepareView(stage: stage, pct: pct, label: label)
            case let .ready(videoURL, artifacts):
                PlayerView(videoURL: videoURL, artifacts: artifacts)
            case let .streaming(player):
                StreamingPlayerView(player: player)
            case let .failed(message):
                FailureView(message: message)
            }
        }
        .frame(minWidth: 720, minHeight: 480)
        // One file picker, usable from any state (start screen, the player, or the File menu).
        .fileImporter(isPresented: $model.showImporter,
                      allowedContentTypes: [.movie, .video, .mpeg4Movie],
                      allowsMultipleSelection: false) { result in
            if case let .success(urls) = result, let url = urls.first { model.open(url) }
        }
        // Closing the window must stop playback and the sidecar — otherwise the audio
        // (and any in-progress preparation) keeps running after the window is gone.
        .onDisappear { model.reset() }
    }
}

struct ChooseView: View {
    @EnvironmentObject var model: AppModel

    var body: some View {
        VStack(spacing: 24) {
            if let logo = AppAsset.image("logo") {
                logo.resizable().scaledToFit().frame(maxWidth: 360)
                    .accessibilityLabel("Lecture AD Player")
            } else {
                Text("Lecture AD Player").font(.largeTitle).bold().foregroundStyle(Color.brandBlue)
            }
            Text("Open a recorded lecture to add audio description.")
                .multilineTextAlignment(.center).foregroundStyle(.secondary)

            VStack(spacing: 8) {
                Picker("Preparation mode", selection: $model.smoothPlayback) {
                    Text("Start sooner").tag(false)
                    Text("Smoothest playback").tag(true)
                }
                .pickerStyle(.segmented)
                .labelsHidden()
                .frame(maxWidth: 360)
                .accessibilityLabel("Preparation mode")
                .accessibilityValue(model.smoothPlayback ? "Smoothest playback" : "Start sooner")
                Text(model.smoothPlayback
                     ? "Prepares the whole lecture first, then plays smoothly with no slowdown."
                     : "Starts after the first part is ready; the rest prepares as you watch.")
                    .font(.caption).foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
                    .accessibilityHidden(true)  // conveyed by the picker's value/hint
            }
            .accessibilityHint(model.smoothPlayback
                ? "Prepares the whole lecture before playback, then plays without using the processor — smoothest while other apps are open."
                : "Starts playing sooner; the rest prepares while you watch.")

            Button("Open Lecture…") { model.requestOpen() }
                .buttonStyle(.borderedProminent)
                .tint(.brandBlue)
                .accessibilityLabel("Open lecture video")
                .accessibilityHint("Choose a lecture video file to prepare audio description")
        }
        .padding(40)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color.white)
    }
}

struct FailureView: View {
    @EnvironmentObject var model: AppModel
    let message: String
    var body: some View {
        VStack(spacing: 16) {
            Text("Preparation failed").font(.title).bold().foregroundStyle(Color.brandBlue)
            Text(message).multilineTextAlignment(.center)
                .accessibilityLabel("Error: \(message)")
            Button("Try another lecture") { model.reset() }
                .buttonStyle(.borderedProminent).tint(.brandBlue)
                .keyboardShortcut(.defaultAction)
        }
        .padding(40)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color.white)
    }
}

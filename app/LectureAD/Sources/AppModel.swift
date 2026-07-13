import SwiftUI

/// App state machine. Drives the accessible progress UI from sidecar events and hands the
/// player finished cached artifacts. Pressing play never reaches the sidecar (§1).
///
/// Default mode is STREAMING (start after window 0); set LADPIPE_STREAM=0 for the batch path.
@MainActor
final class AppModel: ObservableObject {
    enum Phase {
        case idle
        case preparing(stage: String, pct: Double, label: String)
        case ready(videoURL: URL, artifacts: Artifacts)      // batch
        case streaming(player: StreamingPlayer)              // streaming
        case failed(String)
    }

    @Published var phase: Phase = .idle
    @Published var showImporter = false   // drives the file picker from anywhere (menu / button)
    // User's preparation choice on the start screen. false = streaming (start sooner; the rest
    // prepares while you watch, so inference runs during playback). true = batch (prepare the
    // whole lecture first, then play from the cache with NO inference — smoothest on low-RAM
    // Macs). Seeded from the env/config default (LADPIPE_STREAM) in init.
    @Published var smoothPlayback = false
    private let sidecar = SidecarController()
    private let announcer = Announcer()
    private var streamingPlayer: StreamingPlayer?
    // Held while preparing so macOS App Nap can't suspend the app (and its sidecar) when the
    // window loses focus — that was silently freezing long preparations.
    private var activity: NSObjectProtocol?

    init() { smoothPlayback = !useStreaming }

    private func beginActivity() {
        if activity == nil {
            activity = ProcessInfo.processInfo.beginActivity(
                options: [.userInitiated], reason: "Preparing audio description")
        }
    }

    private func endActivity() {
        if let a = activity { ProcessInfo.processInfo.endActivity(a); activity = nil }
    }

    // Dev launch config: env vars (when run from a terminal) OR a bundled dev.json (when
    // launched via `open`, the recommended way — `open` doesn't pass env vars, and a
    // LaunchServices launch is what lets NSAppSleepDisabled actually prevent App Nap).
    private lazy var devConfig: [String: Any] = {
        guard let url = Bundle.main.url(forResource: "dev", withExtension: "json"),
              let data = try? Data(contentsOf: url),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else { return [:] }
        return obj
    }()

    private func setting(_ env: String, _ key: String) -> String? {
        ProcessInfo.processInfo.environment[env] ?? devConfig[key] as? String
    }
    private var sidecarCommand: String { setting("LADPIPE_CMD", "cmd") ?? "/usr/bin/false" }
    private var configPath: String { setting("LADPIPE_CONFIG", "config") ?? "config/default.yaml" }
    private var useMock: Bool { setting("LADPIPE_MOCK", "mock") == "1" }
    private var useStreaming: Bool { setting("LADPIPE_STREAM", "stream") != "0" }

    /// Ask to pick a (new) lecture — works from any state (start screen, player, etc.).
    func requestOpen() { showImporter = true }

    func open(_ videoURL: URL) {
        sidecar.cancel()          // stop any in-progress preparation for the previous lecture
        streamingPlayer = nil
        beginActivity()
        phase = .preparing(stage: "start", pct: 0, label: "Preparing audio description")
        announcer.announce("Preparing audio description", force: true)
        smoothPlayback ? openBatch(videoURL) : openStreaming(videoURL)
    }

    func reset() { sidecar.cancel(); streamingPlayer = nil; endActivity(); phase = .idle }

    // MARK: streaming
    private func openStreaming(_ videoURL: URL) {
        // The player grants a pacing credit (stdin) each time the playhead enters a new
        // window, keeping the engine ~2 windows ahead — so the GPU stays free for playback.
        let player = StreamingPlayer(videoURL: videoURL) { [weak self] in self?.sidecar.grantCredit() }
        streamingPlayer = player
        var args = ["stream", "--video", videoURL.path, "--config", configPath,
                    "--window", "90", "--lookahead", "2", "--json"]
        if useMock { args.append("--mock") }
        sidecar.prepare(command: sidecarCommand, arguments: args) { [weak self] event in
            self?.handleStream(event, player: player)
        }
    }

    private func handleStream(_ event: SidecarEvent, player: StreamingPlayer) {
        switch event {
        case let .progress(stage, pct, label):
            if case .streaming = phase {} else {
                phase = .preparing(stage: stage, pct: pct, label: label)
                announcer.announce("\(label), \(Int(pct * 100)) percent")
            }
        case let .windowReady(window):
            let first = player.totalReady == 0
            Task { await player.addWindow(window) }
            if first {
                announcer.announce("Starting playback. The rest prepares as you watch.", force: true)
                phase = .streaming(player: player)
            }
        case .streamDone:
            endActivity()
            announcer.announce("Whole lecture prepared.")
        case let .error(message):
            endActivity()
            announcer.announce("Preparation failed. \(message)", force: true)
            phase = .failed(message)
        case .done, .cacheHit:
            break  // not emitted in streaming mode
        }
    }

    // MARK: batch
    private func openBatch(_ videoURL: URL) {
        var args = ["run", "--video", videoURL.path, "--config", configPath, "--json"]
        if useMock { args.append("--mock") }
        sidecar.prepare(command: sidecarCommand, arguments: args) { [weak self] event in
            self?.handleBatch(event, videoURL: videoURL)
        }
    }

    private func handleBatch(_ event: SidecarEvent, videoURL: URL) {
        switch event {
        case let .progress(stage, pct, label):
            phase = .preparing(stage: stage, pct: pct, label: label)
            announcer.announce("\(label), \(Int(pct * 100)) percent")
        case let .done(a, c, d, m), let .cacheHit(a, c, d, m):
            endActivity()
            let artifacts = Artifacts(
                audioURL: URL(fileURLWithPath: a), captionsURL: URL(fileURLWithPath: c),
                descriptionsURL: URL(fileURLWithPath: d), extendedAudioURL: extendedAudioURL(a),
                manifestURL: URL(fileURLWithPath: m))
            announcer.announce("Audio description ready. Playing.", force: true)
            phase = .ready(videoURL: videoURL, artifacts: artifacts)
        case let .error(message):
            endActivity()
            announcer.announce("Preparation failed. \(message)", force: true)
            phase = .failed(message)
        case .windowReady, .streamDone:
            break  // not emitted in batch mode
        }
    }

    private func extendedAudioURL(_ audio: String) -> URL? {
        let ext = (audio as NSString).deletingPathExtension + ".ext.wav"
        return FileManager.default.fileExists(atPath: ext) ? URL(fileURLWithPath: ext) : nil
    }
}

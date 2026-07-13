import Foundation

/// One event from the sidecar's newline-delimited JSON protocol (cli.py / §8).
enum SidecarEvent {
    case progress(stage: String, pct: Double, label: String)
    case done(artifact: String, captions: String, descriptions: String, manifest: String)
    case cacheHit(artifact: String, captions: String, descriptions: String, manifest: String)
    case windowReady(window: StreamWindowInfo)
    case streamDone(windows: Int)
    case error(message: String)
}

/// One streamed window (from a `window_ready` event): a time range + its artifacts.
struct StreamWindowInfo {
    let index: Int
    let tStart: Double
    let tEnd: Double
    let audioURL: URL
    let captionsURL: URL
    let descriptionsURL: URL
    var extendedAudioURL: URL? {
        let p = audioURL.deletingPathExtension().appendingPathExtension("ext.wav")
        return FileManager.default.fileExists(atPath: p.path) ? p : nil
    }
}

/// Launches the Python core as a subprocess and streams its JSON events.
/// The player never goes through here — it only reads a finished cached artifact (§1).
final class SidecarController {
    private var process: Process?
    private var stdinHandle: FileHandle?

    /// Grant the streaming engine one more window of lookahead (a credit line on its stdin).
    func grantCredit() {
        stdinHandle?.write("ok\n".data(using: .utf8)!)
    }

    /// Runs `ladpipe run --video <video> --config <config> --json [--mock]`.
    /// `onEvent` is delivered on the main queue. `command` is the sidecar executable
    /// (a bundled frozen binary in release, the dev `ladpipe` in development).
    func prepare(
        command: String,
        arguments: [String],
        onEvent: @escaping (SidecarEvent) -> Void
    ) {
        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: command)
        proc.arguments = arguments
        // Run the heavy ML inference at lower scheduling priority so macOS lets the user's
        // foreground apps take CPU first — preparation is background work the user watches a
        // progress bar for, not something that should make the whole system stutter.
        proc.qualityOfService = .utility
        // A LaunchServices-launched app has a minimal PATH; add Homebrew/usr-local so the
        // sidecar (and anything it shells out to, e.g. ffmpeg) is found.
        var env = ProcessInfo.processInfo.environment
        env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:" + (env["PATH"] ?? "/usr/bin:/bin")
        proc.environment = env
        let stdout = Pipe()
        proc.standardOutput = stdout
        // Send the sidecar's heavy stderr (mlx/whisper/voxtral logs) to a file, NEVER the
        // inherited terminal — a background process writing to the terminal gets SIGTTOU and
        // is stopped, which silently freezes preparation. (JSON errors still arrive on stdout.)
        proc.standardError = Self.logHandle()
        // stdin carries pacing credits (streaming bounded-lookahead).
        let stdin = Pipe()
        proc.standardInput = stdin
        stdinHandle = stdin.fileHandleForWriting

        var buffer = Data()
        stdout.fileHandleForReading.readabilityHandler = { handle in
            buffer.append(handle.availableData)
            while let nl = buffer.firstIndex(of: 0x0A) {
                let line = buffer.subdata(in: buffer.startIndex..<nl)
                buffer.removeSubrange(buffer.startIndex...nl)
                if let event = Self.decode(line) {
                    DispatchQueue.main.async { onEvent(event) }
                }
            }
        }
        proc.terminationHandler = { _ in
            stdout.fileHandleForReading.readabilityHandler = nil
        }
        do {
            try proc.run()
            self.process = proc
        } catch {
            DispatchQueue.main.async {
                onEvent(.error(message: "Could not start the preparation engine: \(error.localizedDescription)"))
            }
        }
    }

    func cancel() {
        process?.terminate()
        process = nil
    }

    /// A file handle for the sidecar's stderr log (~/Library/Logs/LectureAD-sidecar.log),
    /// falling back to /dev/null. Keeps sidecar output off the controlling terminal.
    private static func logHandle() -> Any {
        let dir = FileManager.default.urls(for: .libraryDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("Logs")
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let url = dir.appendingPathComponent("LectureAD-sidecar.log")
        FileManager.default.createFile(atPath: url.path, contents: nil)
        return (try? FileHandle(forWritingTo: url)) ?? FileHandle.nullDevice
    }

    private static func decode(_ line: Data) -> SidecarEvent? {
        guard let obj = try? JSONSerialization.jsonObject(with: line) as? [String: Any],
              let event = obj["event"] as? String else { return nil }
        switch event {
        case "progress":
            return .progress(
                stage: obj["stage"] as? String ?? "",
                pct: obj["pct"] as? Double ?? 0,
                label: obj["label"] as? String ?? "")
        case "done", "cache_hit":
            let a = obj["artifact"] as? String ?? ""
            let c = obj["captions"] as? String ?? ""
            let d = obj["descriptions"] as? String ?? ""
            let m = obj["manifest"] as? String ?? ""
            return event == "done"
                ? .done(artifact: a, captions: c, descriptions: d, manifest: m)
                : .cacheHit(artifact: a, captions: c, descriptions: d, manifest: m)
        case "window_ready":
            return .windowReady(window: StreamWindowInfo(
                index: obj["index"] as? Int ?? 0,
                tStart: obj["t_start"] as? Double ?? 0,
                tEnd: obj["t_end"] as? Double ?? 0,
                audioURL: URL(fileURLWithPath: obj["artifact"] as? String ?? ""),
                captionsURL: URL(fileURLWithPath: obj["captions"] as? String ?? ""),
                descriptionsURL: URL(fileURLWithPath: obj["descriptions"] as? String ?? "")))
        case "stream_done":
            return .streamDone(windows: obj["windows"] as? Int ?? 0)
        case "error":
            return .error(message: obj["message"] as? String ?? "Unknown error")
        default:
            return nil
        }
    }
}

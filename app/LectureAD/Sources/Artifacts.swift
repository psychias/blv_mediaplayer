import Foundation

/// The cached artifact set for a lecture (paths come from the sidecar's done event).
struct Artifacts {
    let audioURL: URL          // length-matched enhanced audio (.wav)
    let captionsURL: URL       // lecturer + gap-AD cues (.vtt)
    let descriptionsURL: URL   // extended-AD / rung-0 cues (.desc.vtt)
    let extendedAudioURL: URL? // concatenated rung-0 clips (.ext.wav), if any
    let manifestURL: URL
}

enum CueKind { case lecturer, ad, extended }

/// One caption cue.
struct Cue: Identifiable {
    let id = UUID()
    let start: Double
    let end: Double
    let text: String
    let kind: CueKind
}

/// Minimal WebVTT parser. Recognises our cue kinds from the identifier (L# / AD# /
/// DESC#) and the `<c.ad>` / `<c.ad-extended>` class, and strips the AD: prefix/tags
/// for display (the player styles AD cues distinctly instead).
enum VTT {
    static func parse(_ url: URL) -> [Cue] {
        guard let text = try? String(contentsOf: url, encoding: .utf8) else { return [] }
        var cues: [Cue] = []
        let blocks = text.components(separatedBy: "\n\n")
        for block in blocks {
            let lines = block.split(separator: "\n", omittingEmptySubsequences: false).map(String.init)
            guard let tIdx = lines.firstIndex(where: { $0.contains("-->") }) else { continue }
            let id = tIdx > 0 ? lines[tIdx - 1] : ""
            let times = lines[tIdx].components(separatedBy: "-->")
            guard times.count == 2,
                  let start = seconds(times[0]), let end = seconds(times[1]) else { continue }
            let raw = lines[(tIdx + 1)...].joined(separator: "\n")
            let kind: CueKind = raw.contains("ad-extended") || id.hasPrefix("DESC")
                ? .extended
                : (raw.contains("<c.ad>") || id.hasPrefix("AD") ? .ad : .lecturer)
            cues.append(Cue(start: start, end: end, text: clean(raw), kind: kind))
        }
        return cues.sorted { $0.start < $1.start }
    }

    private static func clean(_ s: String) -> String {
        var t = s
        for tag in ["<c.ad-extended>", "</c.ad-extended>", "<c.ad>", "</c.ad>"] {
            t = t.replacingOccurrences(of: tag, with: "")
        }
        if t.hasPrefix("AD: ") { t.removeFirst(4) }
        return t.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private static func seconds(_ s: String) -> Double? {
        // HH:MM:SS.mmm (ignore any trailing cue settings)
        let token = s.trimmingCharacters(in: .whitespaces).split(separator: " ").first.map(String.init) ?? ""
        let parts = token.split(separator: ":").map(String.init)
        guard parts.count == 3, let h = Double(parts[0]), let m = Double(parts[1]),
              let sec = Double(parts[2]) else { return nil }
        return h * 3600 + m * 60 + sec
    }
}

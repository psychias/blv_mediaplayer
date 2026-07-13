import SwiftUI

enum CaptionPosition: String, CaseIterable, Identifiable {
    case bottom, top
    var id: String { rawValue }
    var label: String { self == .bottom ? "Bottom" : "Top" }
}

/// Low-vision caption customisation, persisted across launches (§8). Captions are ON by
/// default per the project decision (overrides §8's audio-only default).
/// @Published + UserDefaults (not @AppStorage, which never fires objectWillChange from an
/// ObservableObject — menu checkmarks and remote observers would go stale).
final class CaptionSettings: ObservableObject {
    private let defaults = UserDefaults.standard

    @Published var showLecturer: Bool { didSet { defaults.set(showLecturer, forKey: "showLecturer") } }
    @Published var showAD: Bool { didSet { defaults.set(showAD, forKey: "showAD") } }
    @Published var fontSize: Double { didSet { defaults.set(fontSize, forKey: "fontSize") } }
    @Published var highContrast: Bool { didSet { defaults.set(highContrast, forKey: "highContrast") } }
    @Published var videoZoom: Double { didSet { defaults.set(videoZoom, forKey: "videoZoom") } }
    @Published private var positionRaw: String { didSet { defaults.set(positionRaw, forKey: "position") } }

    init() {
        let d = UserDefaults.standard
        showLecturer = d.object(forKey: "showLecturer") as? Bool ?? true
        showAD = d.object(forKey: "showAD") as? Bool ?? true
        fontSize = d.object(forKey: "fontSize") as? Double ?? 22.0
        highContrast = d.object(forKey: "highContrast") as? Bool ?? true
        videoZoom = d.object(forKey: "videoZoom") as? Double ?? 1.0
        positionRaw = d.string(forKey: "position") ?? CaptionPosition.bottom.rawValue
    }

    var position: CaptionPosition {
        get { CaptionPosition(rawValue: positionRaw) ?? .bottom }
        set { positionRaw = newValue.rawValue }
    }

    func enlarge() { fontSize = min(fontSize + 4, 60) }
    func shrink() { fontSize = max(fontSize - 4, 12) }
    func zoomIn() { videoZoom = min(videoZoom + 0.25, 3.0) }
    func zoomOut() { videoZoom = max(videoZoom - 0.25, 1.0) }
}

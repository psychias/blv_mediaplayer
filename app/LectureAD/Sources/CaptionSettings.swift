import SwiftUI

enum CaptionPosition: String, CaseIterable, Identifiable {
    case bottom, top
    var id: String { rawValue }
    var label: String { self == .bottom ? "Bottom" : "Top" }
}

/// Low-vision caption customisation, persisted across launches (§8). Captions are ON by
/// default per the project decision (overrides §8's audio-only default).
final class CaptionSettings: ObservableObject {
    @AppStorage("showLecturer") var showLecturer = true
    @AppStorage("showAD") var showAD = true
    @AppStorage("fontSize") var fontSize = 22.0
    @AppStorage("highContrast") var highContrast = true
    @AppStorage("position") private var positionRaw = CaptionPosition.bottom.rawValue
    @AppStorage("videoZoom") var videoZoom = 1.0

    var position: CaptionPosition {
        get { CaptionPosition(rawValue: positionRaw) ?? .bottom }
        set { positionRaw = newValue.rawValue }
    }

    func enlarge() { fontSize = min(fontSize + 4, 60) }
    func shrink() { fontSize = max(fontSize - 4, 12) }
}

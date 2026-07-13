import AppKit
import SwiftUI

extension Color {
    /// Brand blue — #0028A5 (R0 G40 B165, Pantone 286 C).
    static let brandBlue = Color(red: 0, green: 40.0 / 255.0, blue: 165.0 / 255.0)
}

/// Loads PNGs bundled into the app's Resources (logo, loading icon).
enum AppAsset {
    static func image(_ name: String) -> Image? {
        guard let ns = nsImage(name) else { return nil }
        return Image(nsImage: ns)
    }

    static func nsImage(_ name: String) -> NSImage? {
        Bundle.main.url(forResource: name, withExtension: "png").flatMap { NSImage(contentsOf: $0) }
    }
}

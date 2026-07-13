import AppKit
import SwiftUI

// WCAG 2.1 AA palette (eCH-0059). Every literal below has a row in
// scripts/contrast_audit.py — add one there whenever a colour is added here.
extension Color {
    /// Brand blue — #0028A5 (R0 G40 B165, Pantone 286 C). 11.37:1 on white.
    static let brandBlue = Color(red: 0, green: 40.0 / 255.0, blue: 165.0 / 255.0)
    /// Secondary text — #595959, 7.00:1 on white (system .secondary is only ~4:1).
    static let textSecondary = Color(red: 0x59 / 255.0, green: 0x59 / 255.0, blue: 0x59 / 255.0)
    /// Solid control-bar background — #F5F5F5 (replaces .regularMaterial, whose
    /// translucency makes contrast indeterminate). brandBlue on it: 10.43:1.
    static let barBackground = Color(red: 0xF5 / 255.0, green: 0xF5 / 255.0, blue: 0xF5 / 255.0)
    /// Caption AD text — #FFFF00 on the black caption pill (>= 0.8 opacity): 11.77:1 worst case.
    static let captionYellow = Color(red: 1, green: 1, blue: 0)
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

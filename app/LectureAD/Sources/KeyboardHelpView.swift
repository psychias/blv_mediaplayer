import SwiftUI

/// The "?" / ⌘/ keyboard-shortcut reference. Plain Text rows (VoiceOver-readable), AA
/// colours from Theme. Keep this table in sync with AppCommands.swift.
struct KeyboardHelpView: View {
    @EnvironmentObject private var model: AppModel

    private static let sections: [(title: String, rows: [(action: String, single: String, menu: String)])] = [
        ("Playback", [
            ("Play or pause", "Space or K", "⌥⌘P"),
            ("Back / forward 15 seconds", "J / L", "⌥⌘J / ⌥⌘L"),
            ("Back / forward 5 seconds", "← / →", "⌥⌘← / ⌥⌘→"),
            ("Mute or unmute", "M", "⌥⌘U"),
            ("Open another lecture", "—", "⌘O"),
        ]),
        ("Audio Description", [
            ("Play the offered description now", "D", "⇧⌘D"),
            ("Skip the description being spoken", "X", "⌥⌘X"),
            ("Replay the last description", "R", "⌥⌘R"),
            ("Timing: Automatic / On-Demand / Off", "—", "⌥⌘1 / ⌥⌘2 / ⌥⌘3"),
            ("Detail: Brief / Standard / Detailed", "—", "⌥⌘7 / ⌥⌘8 / ⌥⌘9"),
        ]),
        ("Captions & View", [
            ("Lecturer captions on/off", "C", "⌥⌘C"),
            ("AD captions on/off", "A", "⌥⌘A"),
            ("High-contrast captions on/off", "H", "⌃⌘H"),
            ("Larger / smaller captions", "—", "⌘= / ⌘−"),
            ("Zoom video in / out", "—", "⇧⌘= / ⇧⌘−"),
        ]),
        ("Help", [
            ("This shortcut list", "?", "⌘/"),
            ("Close this list", "Esc", "—"),
        ]),
    ]

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Text("Keyboard Shortcuts").font(.title2).bold()
                    .foregroundStyle(Color.brandBlue)
                Spacer()
                Button("Close") { model.showKeyboardHelp = false }
                    .keyboardShortcut(.cancelAction)
            }
            .padding()
            Divider()
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    Text("Single keys work while the player is on screen and can be turned "
                         + "off in Playback → Single-Key Shortcuts. Menu shortcuts always work.")
                        .font(.callout)
                        .foregroundStyle(Color.textSecondary)
                    ForEach(Self.sections, id: \.title) { section in
                        VStack(alignment: .leading, spacing: 6) {
                            Text(section.title).font(.headline).foregroundStyle(Color.brandBlue)
                            ForEach(section.rows, id: \.action) { row in
                                HStack(alignment: .firstTextBaseline) {
                                    Text(row.action).frame(maxWidth: .infinity, alignment: .leading)
                                    Text(row.single).monospaced()
                                        .frame(width: 120, alignment: .trailing)
                                    Text(row.menu).monospaced()
                                        .frame(width: 150, alignment: .trailing)
                                }
                                .accessibilityElement(children: .combine)
                                .accessibilityLabel(
                                    "\(row.action). Key: \(row.single). Menu shortcut: \(row.menu).")
                            }
                        }
                    }
                }
                .padding()
            }
        }
        .frame(minWidth: 560, minHeight: 460)
        .background(Color.white)
    }
}

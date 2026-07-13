import SwiftUI

/// Full menu-bar coverage so every action is keyboard-discoverable and operable without a
/// mouse (WCAG 2.1.1). Single-character player keys live in PlayerShortcutLayer below and
/// can be turned off (WCAG 2.1.4); the menu shortcuts here always carry modifiers.
/// @ObservedObject inside a Commands struct is what keeps checkmarks/enabled states live.
struct PlaybackCommands: Commands {
    @ObservedObject var model: AppModel

    var body: some Commands {
        CommandMenu("Playback") {
            Button("Play/Pause") { model.playPause() }
                .keyboardShortcut("p", modifiers: [.option, .command])
                .disabled(model.activeTransport == nil)
            Button("Back 15 Seconds") { model.skipBack15() }
                .keyboardShortcut("j", modifiers: [.option, .command])
                .disabled(model.activeTransport == nil)
            Button("Forward 15 Seconds") { model.skipForward15() }
                .keyboardShortcut("l", modifiers: [.option, .command])
                .disabled(model.activeTransport == nil)
            Button("Back 5 Seconds") { model.seekBack5() }
                .keyboardShortcut(.leftArrow, modifiers: [.option, .command])
                .disabled(model.activeTransport == nil)
            Button("Forward 5 Seconds") { model.seekForward5() }
                .keyboardShortcut(.rightArrow, modifiers: [.option, .command])
                .disabled(model.activeTransport == nil)
            Button("Mute/Unmute") { model.toggleMute() }
                .keyboardShortcut("u", modifiers: [.option, .command])
                .disabled(model.activeTransport == nil)
            Divider()
            Toggle("Single-Key Shortcuts (Space, J, K, L…)", isOn: $model.singleKeyShortcuts)
        }
    }
}

struct AudioDescriptionCommands: Commands {
    @ObservedObject var model: AppModel

    private var timingBinding: Binding<ADScheduler.Mode> {
        Binding(get: { model.adMode }, set: { model.adMode = $0 })
    }
    private var verbosityBinding: Binding<AppModel.Verbosity> {
        Binding(get: { model.verbosity }, set: { model.setVerbosity($0) })
    }

    var body: some Commands {
        CommandMenu("Audio Description") {
            Picker("Description Timing", selection: timingBinding) {
                Text("Automatic (pause and describe)").tag(ADScheduler.Mode.auto)
                    .keyboardShortcut("1", modifiers: [.option, .command])
                Text("On-Demand (press D when offered)").tag(ADScheduler.Mode.onDemand)
                    .keyboardShortcut("2", modifiers: [.option, .command])
                Text("Off").tag(ADScheduler.Mode.off)
                    .keyboardShortcut("3", modifiers: [.option, .command])
            }
            .pickerStyle(.inline)
            Divider()
            // ⇧⌘D, not ⌥⌘D — the latter is the system Dock toggle.
            Button("Play Description Now") { model.playDescriptionNow() }
                .keyboardShortcut("d", modifiers: [.shift, .command])
                .disabled(model.activeTransport == nil)
            Button("Skip Description") { model.skipDescription() }
                .keyboardShortcut("x", modifiers: [.option, .command])
                .disabled(model.activeTransport == nil)
            Button("Replay Last Description") { model.replayDescription() }
                .keyboardShortcut("r", modifiers: [.option, .command])
                .disabled(model.activeTransport == nil)
            Divider()
            Picker("Description Detail", selection: verbosityBinding) {
                Text("Brief").tag(AppModel.Verbosity.brief)
                    .keyboardShortcut("7", modifiers: [.option, .command])
                Text("Standard").tag(AppModel.Verbosity.standard)
                    .keyboardShortcut("8", modifiers: [.option, .command])
                Text("Detailed").tag(AppModel.Verbosity.detailed)
                    .keyboardShortcut("9", modifiers: [.option, .command])
            }
            .pickerStyle(.inline)
        }
    }
}

/// Caption + zoom commands, inserted into the system View menu.
struct CaptionCommands: Commands {
    @ObservedObject var model: AppModel
    @ObservedObject var settings: CaptionSettings

    private var positionBinding: Binding<CaptionPosition> {
        Binding(get: { settings.position }, set: { settings.position = $0 })
    }

    var body: some Commands {
        CommandGroup(after: .toolbar) {
            Divider()
            Toggle("Lecturer Captions", isOn: $settings.showLecturer)
                .keyboardShortcut("c", modifiers: [.option, .command])
            Toggle("AD Captions", isOn: $settings.showAD)
                .keyboardShortcut("a", modifiers: [.option, .command])
            Toggle("High-Contrast Captions", isOn: $settings.highContrast)
                .keyboardShortcut("h", modifiers: [.control, .command])
            Button("Larger Captions") { settings.enlarge() }
                .keyboardShortcut("=", modifiers: .command)
            Button("Smaller Captions") { settings.shrink() }
                .keyboardShortcut("-", modifiers: .command)
            Picker("Caption Position", selection: positionBinding) {
                ForEach(CaptionPosition.allCases) { Text($0.label).tag($0) }
            }
            Divider()
            Button("Zoom In Video") { settings.zoomIn() }
                .keyboardShortcut("=", modifiers: [.shift, .command])
            Button("Zoom Out Video") { settings.zoomOut() }
                .keyboardShortcut("-", modifiers: [.shift, .command])
        }
    }
}

struct HelpCommands: Commands {
    @ObservedObject var model: AppModel

    var body: some Commands {
        CommandGroup(replacing: .help) {
            Button("Keyboard Shortcuts") { model.toggleHelp() }
                .keyboardShortcut("/", modifiers: .command)
        }
    }
}

/// Invisible in-window carrier for the single-character player shortcuts (YouTube-style).
/// Lives inside the player views only, so the keys are active exactly while a player is on
/// screen and never in the file picker. Zero frame + .clipped() (NOT .hidden()/opacity(0),
/// which can drop shortcut registration). The whole layer honours the WCAG 2.1.4 toggle
/// except the arrows (not printable characters, so exempt).
struct PlayerShortcutLayer: View {
    @EnvironmentObject private var model: AppModel
    @EnvironmentObject private var settings: CaptionSettings

    var body: some View {
        Group {
            shortcut(.leftArrow) { model.seekBack5() }
            shortcut(.rightArrow) { model.seekForward5() }
            if model.singleKeyShortcuts {
                shortcut(.space) { model.playPause() }
                shortcut("k") { model.playPause() }
                shortcut("j") { model.skipBack15() }
                shortcut("l") { model.skipForward15() }
                shortcut("m") { model.toggleMute() }
                shortcut("d") { model.playDescriptionNow() }
                shortcut("x") { model.skipDescription() }
                shortcut("r") { model.replayDescription() }
                shortcut("c") { settings.showLecturer.toggle() }
                shortcut("a") { settings.showAD.toggle() }
                shortcut("h") { settings.highContrast.toggle() }
                shortcut("?") { model.toggleHelp() }
            }
        }
        .frame(width: 0, height: 0)
        .clipped()
        .accessibilityHidden(true)
    }

    private func shortcut(_ key: KeyEquivalent, action: @escaping () -> Void) -> some View {
        Button("", action: action)
            .keyboardShortcut(key, modifiers: [])
            .buttonStyle(.plain)
            .focusable(false)
    }
}

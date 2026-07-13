import SwiftUI

/// Caption overlay shared by the batch and streaming players: lecturer + AD cues styled
/// distinctly, toggleable and sized per CaptionSettings (§8).
struct CaptionsOverlay: View {
    let lecturer: Cue?
    let ad: Cue?
    let extended: Cue?
    let inExtended: Bool
    @ObservedObject var settings: CaptionSettings

    var body: some View {
        VStack {
            if settings.position == .top { cues; Spacer() } else { Spacer(); cues }
        }
        .padding(24)
    }

    private var cues: some View {
        VStack(spacing: 6) {
            if inExtended, let e = extended {
                line("AD: \(e.text)", color: .captionYellow, label: "Audio description")
            }
            if settings.showAD, !inExtended, let a = ad {
                line("AD: \(a.text)", color: .captionYellow, label: "Audio description")
            }
            if settings.showLecturer, let l = lecturer {
                line(l.text, color: .white, label: "Lecturer")
            }
        }
    }

    private func line(_ s: String, color: Color, label: String) -> some View {
        Text(s)
            .font(.system(size: settings.fontSize, weight: .semibold))
            .foregroundStyle(color)
            .padding(.horizontal, 12).padding(.vertical, 6)
            // 0.8 is the audited AA floor over a worst-case (white) video frame; anything
            // lower drops caption contrast below 4.5:1 (see scripts/contrast_audit.py).
            .background(Color.black.opacity(settings.highContrast ? 0.95 : 0.8))
            .clipShape(RoundedRectangle(cornerRadius: 6))
            .accessibilityLabel("\(label): \(s.replacingOccurrences(of: "AD: ", with: ""))")
    }
}

/// Standard, labelled, keyboard-operable transport (§8).
struct TransportControls: View {
    let isPlaying: Bool
    let isMuted: Bool
    let currentTime: Double
    let duration: Double
    let onPlayPause: () -> Void
    let onSkip: (Double) -> Void
    let onSeek: (Double) -> Void
    let onMute: () -> Void
    let onOpen: () -> Void
    let onSearch: () -> Void
    @FocusState private var playFocused: Bool

    var body: some View {
        HStack(spacing: 16) {
            // Shortcuts live in PlayerShortcutLayer + the menu bar (single source of truth),
            // not on these buttons — double registration would fire actions twice.
            iconButton("Open another lecture", "folder.badge.plus", action: onOpen)
            iconButton("Find in lecture", "magnifyingglass", action: onSearch)
                .keyboardShortcut("f", modifiers: .command)
            Divider().frame(height: 18)
            iconButton("Back 15 seconds", "gobackward.15") { onSkip(-15) }
            iconButton(isPlaying ? "Pause" : "Play", isPlaying ? "pause.fill" : "play.fill",
                       action: onPlayPause)
                .focused($playFocused)
            iconButton("Forward 15 seconds", "goforward.15") { onSkip(15) }
            iconButton(isMuted ? "Unmute" : "Mute",
                       isMuted ? "speaker.slash.fill" : "speaker.wave.2.fill", action: onMute)
            Slider(value: Binding(get: { currentTime }, set: onSeek), in: 0...max(1, duration))
                .accessibilityLabel("Seek")
                .accessibilityValue(timeString(currentTime))
            Text(timeString(currentTime)).monospacedDigit().accessibilityHidden(true)
        }
        .padding(12)
        .frame(maxWidth: .infinity)
        .background(Color.barBackground)   // solid, AA-audited (material is indeterminate)
        .overlay(alignment: .top) { Divider() }
        .tint(.brandBlue)
        .defaultFocus($playFocused, true)  // keyboard users land on Play/Pause first
    }
}

/// Low-vision caption customisation bar (§8).
struct CaptionControlBar: View {
    @ObservedObject var settings: CaptionSettings
    let onZoom: (Double) -> Void

    var body: some View {
        HStack(spacing: 14) {
            Toggle("Lecturer captions", isOn: $settings.showLecturer)
            Toggle("AD captions", isOn: $settings.showAD)
            Divider().frame(height: 18)
            iconButton("Smaller captions", "textformat.size.smaller") { settings.shrink() }
            iconButton("Larger captions", "textformat.size.larger") { settings.enlarge() }
            Toggle("High contrast", isOn: $settings.highContrast)
            Picker("Caption position", selection: $settings.position) {
                ForEach(CaptionPosition.allCases) { Text($0.label).tag($0) }
            }.frame(width: 140)
            Divider().frame(height: 18)
            iconButton("Zoom out", "minus.magnifyingglass") { onZoom(-0.25) }
            iconButton("Zoom in", "plus.magnifyingglass") { onZoom(0.25) }
        }
        .toggleStyle(.checkbox)
        .padding(12)
        .frame(maxWidth: .infinity)
        .background(Color.barBackground)   // solid, AA-audited (material is indeterminate)
        .overlay(alignment: .top) { Divider() }
        .tint(.brandBlue)
    }
}

/// On-demand AD indicator: a description is waiting for the D key (§8). White on brandBlue
/// (11.37:1, audited in scripts/contrast_audit.py).
struct DescriptionAvailableBadge: View {
    var body: some View {
        VStack {
            HStack {
                Spacer()
                Text("Description available — press D")
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(.white)
                    .padding(.horizontal, 12).padding(.vertical, 8)
                    .background(Color.brandBlue)
                    .clipShape(Capsule())
                    .accessibilityLabel("Audio description available. Press D to hear it.")
            }
            Spacer()
        }
        .padding(16)
    }
}

func iconButton(_ label: String, _ system: String, action: @escaping () -> Void) -> some View {
    Button(action: action) { Image(systemName: system) }
        .accessibilityLabel(label)
        .help(label)
}

func timeString(_ t: Double) -> String {
    let s = Int(max(0, t)); return String(format: "%d:%02d", s / 60, s % 60)
}

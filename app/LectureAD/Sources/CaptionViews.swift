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
                line("AD: \(e.text)", color: .yellow, label: "Audio description")
            }
            if settings.showAD, !inExtended, let a = ad {
                line("AD: \(a.text)", color: .yellow, label: "Audio description")
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
            .background(Color.black.opacity(settings.highContrast ? 0.85 : 0.4))
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

    var body: some View {
        HStack(spacing: 16) {
            iconButton("Open another lecture", "folder.badge.plus", action: onOpen)
            iconButton("Find in lecture", "magnifyingglass", action: onSearch)
                .keyboardShortcut("f", modifiers: .command)
            Divider().frame(height: 18)
            iconButton("Back 15 seconds", "gobackward.15") { onSkip(-15) }
                .keyboardShortcut("j", modifiers: [])
            iconButton(isPlaying ? "Pause" : "Play", isPlaying ? "pause.fill" : "play.fill",
                       action: onPlayPause)
                .keyboardShortcut(.space, modifiers: [])
                .keyboardShortcut("k", modifiers: [])  // also k (play/pause)
            iconButton("Forward 15 seconds", "goforward.15") { onSkip(15) }
                .keyboardShortcut("l", modifiers: [])
            iconButton(isMuted ? "Unmute" : "Mute",
                       isMuted ? "speaker.slash.fill" : "speaker.wave.2.fill", action: onMute)
                .keyboardShortcut("m", modifiers: [])
            Slider(value: Binding(get: { currentTime }, set: onSeek), in: 0...max(1, duration))
                .accessibilityLabel("Seek")
                .accessibilityValue(timeString(currentTime))
            Text(timeString(currentTime)).monospacedDigit().accessibilityHidden(true)
        }
        .padding(12)
        .frame(maxWidth: .infinity)
        .background(.regularMaterial)   // neutral bar (not blue), blue accents only
        .tint(.brandBlue)
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
        .background(.regularMaterial)   // neutral bar (not blue), blue accents only
        .tint(.brandBlue)
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

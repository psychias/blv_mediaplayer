import SwiftUI

/// Find-in-lecture (⌘F): text search over the transcript and description cues; choosing a
/// match seeks the player there. Content-based navigation ("jump to the slide about X")
/// instead of time-based scrubbing — the MAVP study found BLV users navigate by content.
/// Searches only the cached cues; no model, no inference (§1).
struct SearchSheet: View {
    let cues: [Cue]            // lecturer + AD + extended, already parsed by the player
    let onJump: (Double) -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var query = ""
    @FocusState private var fieldFocused: Bool

    private var matches: [Cue] {
        let q = query.trimmingCharacters(in: .whitespaces)
        guard q.count >= 2 else { return [] }
        return Array(cues.filter { $0.text.localizedCaseInsensitiveContains(q) }.prefix(50))
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            TextField("Search the lecture", text: $query)
                .textFieldStyle(.roundedBorder)
                .focused($fieldFocused)
                .accessibilityLabel("Search the lecture transcript and descriptions")
                .onSubmit { if let first = matches.first { jump(first) } }
            if matches.isEmpty {
                Text(query.trimmingCharacters(in: .whitespaces).count >= 2
                     ? "No matches"
                     : "Type to search what was said and described")
                    .foregroundStyle(.secondary)
                    .frame(maxHeight: .infinity, alignment: .top)
            } else {
                List(matches) { cue in
                    Button { jump(cue) } label: {
                        HStack(alignment: .firstTextBaseline, spacing: 8) {
                            Text(timeString(cue.start))
                                .monospacedDigit().foregroundStyle(.secondary)
                            Text(kindLabel(cue.kind))
                                .font(.caption).foregroundStyle(cue.kind == .lecturer ? .white : .yellow)
                                .padding(.horizontal, 5).padding(.vertical, 1)
                                .background(Color.black.opacity(0.5))
                                .clipShape(RoundedRectangle(cornerRadius: 4))
                            Text(cue.text).lineLimit(2)
                        }
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("\(kindLabel(cue.kind)) at \(timeString(cue.start)): \(cue.text)")
                    .accessibilityHint("Jumps the lecture there")
                }
                .listStyle(.plain)
            }
            HStack {
                Spacer()
                Button("Close") { dismiss() }.keyboardShortcut(.cancelAction)
            }
        }
        .padding(16)
        .frame(width: 480, height: 380)
        .onAppear { fieldFocused = true }
    }

    private func jump(_ cue: Cue) {
        onJump(cue.start)
        dismiss()
    }

    private func kindLabel(_ kind: CueKind) -> String {
        switch kind {
        case .lecturer: return "Lecturer"
        case .ad, .extended: return "AD"
        }
    }
}

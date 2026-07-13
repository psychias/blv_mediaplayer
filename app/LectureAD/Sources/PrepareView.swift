import SwiftUI

/// Accessible preparation progress. The percentage is announced via VoiceOver (AppModel),
/// not only shown; the loading icon spins while we wait for the lecture to be prepared.
struct PrepareView: View {
    let stage: String
    let pct: Double
    let label: String
    @State private var spinning = false

    var body: some View {
        VStack(spacing: 22) {
            if let icon = AppAsset.image("loading_icon") {
                icon.resizable().scaledToFit().frame(width: 96, height: 96)
                    .rotationEffect(.degrees(spinning ? 360 : 0))
                    .animation(.linear(duration: 1.2).repeatForever(autoreverses: false), value: spinning)
                    .onAppear { spinning = true }
                    .accessibilityHidden(true)
            } else {
                ProgressView().controlSize(.large)
            }
            Text("Preparing audio description…").font(.title2).bold()
                .foregroundStyle(Color.brandBlue)
            ProgressView(value: pct)
                .tint(.brandBlue)
                .frame(maxWidth: 400)
                .accessibilityLabel("Preparation progress")
                .accessibilityValue("\(Int(pct * 100)) percent")
            Text(label).foregroundStyle(Color.textSecondary)
        }
        .padding(40)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color.white)
        // One live region so VoiceOver users hear the current step + percentage.
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(.updatesFrequently)
        .accessibilityLabel("\(label), \(Int(pct * 100)) percent")
    }
}

import SwiftUI

/// Single-window media player: closing the window quits the app (like QuickTime), so playback
/// and the preparation sidecar can't keep running headless after the window is gone.
final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
}

@main
struct LectureADApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    @StateObject private var model = AppModel()
    @StateObject private var captionSettings = CaptionSettings()

    var body: some Scene {
        WindowGroup("Lecture AD Player") {
            ContentView()
                .environmentObject(model)
                .environmentObject(captionSettings)
                .preferredColorScheme(.light)   // white app, regardless of system dark mode
                .tint(.brandBlue)
        }
        .windowResizability(.contentMinSize)
        .commands {
            CommandGroup(replacing: .newItem) {
                Button("Open Lecture…") { model.requestOpen() }
                    .keyboardShortcut("o", modifiers: .command)
            }
        }
    }
}

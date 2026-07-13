import SwiftUI

/// Single-window media player: closing the window quits the app (like QuickTime), so playback
/// and the preparation sidecar can't keep running headless after the window is gone.
final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationWillFinishLaunching(_ notification: Notification) {
        // Writing a pacing credit to a sidecar that has already exited (e.g. after
        // stream_done) raises SIGPIPE, which by default terminates the app before the
        // write's EPIPE ever surfaces as a Swift error. Ignore it so those writes fail
        // harmlessly through `try?` as SidecarController.grantCredit already intends.
        signal(SIGPIPE, SIG_IGN)
    }

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
            PlaybackCommands(model: model)
            AudioDescriptionCommands(model: model)
            CaptionCommands(model: model, settings: captionSettings)
            HelpCommands(model: model)
        }
    }
}

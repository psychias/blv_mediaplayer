import AppKit

/// Throttled VoiceOver announcements so progress is heard, not only shown (§8), without
/// spamming. Posts an accessibility announcement at most every `minInterval` seconds.
final class Announcer {
    private var lastSpoken = Date.distantPast
    private let minInterval: TimeInterval

    init(minInterval: TimeInterval = 4.0) {
        self.minInterval = minInterval
    }

    /// `force` bypasses throttling for milestone messages (done / error).
    func announce(_ message: String, force: Bool = false) {
        let now = Date()
        guard force || now.timeIntervalSince(lastSpoken) >= minInterval else { return }
        lastSpoken = now
        NSAccessibility.post(
            element: NSApp as Any,
            notification: .announcementRequested,
            userInfo: [
                .announcement: message,
                .priority: NSAccessibilityPriorityLevel.high.rawValue,
            ])
    }
}

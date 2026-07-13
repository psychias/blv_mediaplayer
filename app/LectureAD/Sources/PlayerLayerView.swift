import AVFoundation
import AppKit
import SwiftUI

/// Shows the player's video frames only (no native controls) so the app owns the accessible
/// transport and caption overlays. `zoom` enlarges the frame for residual-vision users (§8).
struct PlayerLayerView: NSViewRepresentable {
    let player: AVPlayer
    var zoom: Double

    func makeNSView(context: Context) -> PlayerLayerNSView {
        let view = PlayerLayerNSView()
        view.playerLayer.player = player
        view.playerLayer.videoGravity = .resizeAspect
        return view
    }

    func updateNSView(_ view: PlayerLayerNSView, context: Context) {
        view.layer?.sublayerTransform = CATransform3DMakeScale(zoom, zoom, 1)
    }
}

final class PlayerLayerNSView: NSView {
    let playerLayer = AVPlayerLayer()
    override init(frame: NSRect) {
        super.init(frame: frame)
        wantsLayer = true
        layer?.backgroundColor = NSColor.black.cgColor
        layer?.addSublayer(playerLayer)
    }
    required init?(coder: NSCoder) { fatalError() }
    override func layout() {
        super.layout()
        playerLayer.frame = bounds
    }
}

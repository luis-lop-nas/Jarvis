import AppKit
import MetalKit

final class AppDelegate: NSObject, NSApplicationDelegate {

    private var window:     NSWindow!
    private var metalView:  MTKView!
    private var renderer:   Renderer!
    private var cycleTimer: Timer?

    // Phase-1 demo: auto-cycle states to show all 4 palettes
    private let statesCycle = ["idle", "listening", "thinking", "acting"]
    private var stateIdx    = 0

    // MARK: - Launch

    func applicationDidFinishLaunching(_ notification: Notification) {
        guard let screen = NSScreen.main else { fatalError("no main screen") }
        guard let gpu    = MTLCreateSystemDefaultDevice() else { fatalError("Metal unsupported") }

        let frame = screen.frame

        // ── Transparent always-on-top window ──────────────────────────────────
        window = NSWindow(
            contentRect: frame,
            styleMask:   [.borderless],
            backing:     .buffered,
            defer:       false
        )
        window.level              = NSWindow.Level(rawValue: 1000)
        window.backgroundColor    = .clear
        window.isOpaque           = false
        window.hasShadow          = false
        window.collectionBehavior = [.canJoinAllSpaces, .stationary, .ignoresCycle]
        window.ignoresMouseEvents = true

        // ── MTKView (transparent Metal surface) ───────────────────────────────
        metalView = MTKView(frame: frame, device: gpu)
        metalView.colorPixelFormat         = .bgra8Unorm
        metalView.clearColor               = MTLClearColorMake(0, 0, 0, 0)
        metalView.preferredFramesPerSecond = 60
        metalView.isPaused                 = false
        metalView.enableSetNeedsDisplay    = false

        if let ml = metalView.layer as? CAMetalLayer { ml.isOpaque = false }

        // ── Renderer ──────────────────────────────────────────────────────────
        renderer          = Renderer(device: gpu, logicalSize: frame.size)
        metalView.delegate = renderer

        window.contentView = metalView
        window.makeKeyAndOrderFront(nil)

        print("● JarvisOverlay  Phase 1 — Metal particle cloud")
        print("  Screen: \(Int(frame.width))×\(Int(frame.height))  @60fps")
        print("  States cycle every 3 s.  Cmd-Q / Ctrl-C to quit.\n")

        // Cycle all 4 palettes every 3 s
        cycleTimer = Timer.scheduledTimer(withTimeInterval: 3.0, repeats: true) { [weak self] _ in
            guard let self else { return }
            self.stateIdx = (self.stateIdx + 1) % self.statesCycle.count
            let s = self.statesCycle[self.stateIdx]
            self.renderer.particles.setState(s)
            print("  → \(s)")
        }
    }

    func applicationWillTerminate(_ notification: Notification) {
        cycleTimer?.invalidate()
    }
}

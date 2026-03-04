import AppKit
import MetalKit

// MARK: - AppDelegate ─────────────────────────────────────────────────────────
final class AppDelegate: NSObject, NSApplicationDelegate {

    // MARK: - UI components
    private var window:     NSWindow!
    private var metalView:  MTKView!
    private var renderer:   Renderer!
    private var notchView:  NotchAnimationView!

    // MARK: - IPC
    private var ipcServer: IPCServer!

    // MARK: - Launch ───────────────────────────────────────────────────────────

    func applicationDidFinishLaunching(_ notification: Notification) {
        guard let screen = NSScreen.main else { fatalError("no main screen") }
        guard let gpu    = MTLCreateSystemDefaultDevice() else { fatalError("Metal unsupported") }

        let frame = screen.frame

        // ── Transparent always-on-top overlay window ──────────────────────────
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
        window.ignoresMouseEvents = true   // click-through for the whole overlay

        // ── Metal particle view (fills entire screen) ─────────────────────────
        metalView                             = MTKView(frame: frame, device: gpu)
        metalView.colorPixelFormat            = .bgra8Unorm
        metalView.clearColor                  = MTLClearColorMake(0, 0, 0, 0)
        metalView.preferredFramesPerSecond    = 60
        metalView.isPaused                    = false
        metalView.enableSetNeedsDisplay       = false
        if let ml = metalView.layer as? CAMetalLayer { ml.isOpaque = false }

        renderer           = Renderer(device: gpu, logicalSize: frame.size)
        metalView.delegate = renderer

        window.contentView = metalView

        // ── Notch animation view (sits on top of the Metal surface) ───────────
        notchView = NotchAnimationView(screen: screen)
        metalView.addSubview(notchView)

        window.makeKeyAndOrderFront(nil)

        print("● JarvisOverlay Phase 2")
        print("  Screen: \(Int(frame.width))×\(Int(frame.height))  Metal@60fps")
        print("  Notch: ready")

        // ── IPC server ────────────────────────────────────────────────────────
        ipcServer          = IPCServer()
        ipcServer.delegate = self
        ipcServer.start()

        print("  IPC: ready — waiting for Python daemon\n")
    }

    func applicationWillTerminate(_ notification: Notification) {
        ipcServer?.stop()
    }
}

// MARK: - IPCServerDelegate ───────────────────────────────────────────────────
extension AppDelegate: IPCServerDelegate {

    func ipcServer(_ server: IPCServer, didReceiveCommand command: String,
                   payload: [String: Any])
    {
        // All UI mutations happen here on the main thread (guaranteed by IPCServer)
        switch command {

        // ── Particle cloud + notch state ─────────────────────────────────────
        case "set_state":
            guard let rawState = payload["state"] as? String else { return }
            let amplitude = (payload["amplitude"] as? Double).map { Float($0) } ?? 0.5

            // Particle system accepts "idle/listening/thinking/acting/error"
            renderer.particles.setState(rawState)

            // Notch maps "acting" → .speaking and handles "speaking" directly
            let notchState = NotchState.fromParticleState(rawState)
            notchView.setState(notchState, amplitude: amplitude)

        // ── Notch-only commands (Python bridge notch_* methods) ──────────────
        case "notch_state":
            let rawState  = payload["state"]     as? String ?? "idle"
            let amplitude = (payload["amplitude"] as? Double).map { Float($0) } ?? 0.5
            if let state  = NotchState(rawValue: rawState) {
                notchView.setState(state, amplitude: amplitude)
            }

        case "notch_alert":
            let msg = payload["message"] as? String ?? ""
            notchView.triggerAlert(message: msg)

        // ── Audio level (expands particle cloud + wave amplitude) ─────────────
        case "set_audio_level":
            if let level = payload["level"] as? Double {
                renderer.particles.setAudioLevel(Float(level))
                // Also push amplitude to notch if currently in a wave state
                if [NotchState.listening, .speaking].contains(notchView.currentState) {
                    notchView.setState(notchView.currentState, amplitude: Float(level))
                }
            }

        // ── Particle cloud position ───────────────────────────────────────────
        case "fly_to":
            if let x = payload["x"] as? Double, let y = payload["y"] as? Double {
                renderer.particles.centerX = Float(x)
                renderer.particles.centerY = Float(y)
            }

        case "return_home":
            let c = renderer.particles
            c.centerX = Float(window.frame.width  / 2)
            c.centerY = Float(window.frame.height / 2)

        // ── HUD (stub — extend when HUD view is added) ────────────────────────
        case "say", "hide_hud", "wrap_window":
            // Future: route to HUD view
            print("[AppDelegate] Stub: \(command)")

        default:
            print("[AppDelegate] Unknown command: \(command)")
        }
    }
}


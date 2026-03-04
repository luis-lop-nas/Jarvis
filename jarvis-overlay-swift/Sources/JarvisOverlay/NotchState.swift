import AppKit

// MARK: - NotchState ──────────────────────────────────────────────────────────
/// Visual state of the notch animation. Maps 1-to-1 with JARVIS agent states.
enum NotchState: String, Equatable {
    case idle
    case listening
    case thinking
    case speaking   // maps from "acting" in the particle system
    case alert
}

// MARK: - Color palettes (mirrors kPalettes in ParticleSystem.swift) ──────────

extension NotchState {

    /// Primary accent color (r, g, b components in sRGB linear)
    var accentColor: NSColor {
        switch self {
        case .idle:      return NSColor(srgbRed: 0.000, green: 1.000, blue: 0.878, alpha: 1)
        case .listening: return NSColor(srgbRed: 0.000, green: 1.000, blue: 0.533, alpha: 1)
        case .thinking:  return NSColor(srgbRed: 1.000, green: 0.882, blue: 0.000, alpha: 1)
        case .speaking:  return NSColor(srgbRed: 1.000, green: 0.125, blue: 0.376, alpha: 1)
        case .alert:     return NSColor(srgbRed: 1.000, green: 0.600, blue: 0.000, alpha: 1)
        }
    }

    /// Secondary / glow color
    var glowColor: NSColor {
        switch self {
        case .idle:      return NSColor(srgbRed: 0.482, green: 0.188, blue: 1.000, alpha: 1)
        case .listening: return NSColor(srgbRed: 0.000, green: 1.000, blue: 0.878, alpha: 1)
        case .thinking:  return NSColor(srgbRed: 1.000, green: 0.549, blue: 0.000, alpha: 1)
        case .speaking:  return NSColor(srgbRed: 0.545, green: 0.000, blue: 1.000, alpha: 1)
        case .alert:     return NSColor(srgbRed: 1.000, green: 0.800, blue: 0.000, alpha: 1)
        }
    }

    /// Expanded notch pill size for this state (logical points)
    var pillSize: CGSize {
        switch self {
        case .idle:      return CGSize(width: 126, height: 37)
        case .listening: return CGSize(width: 310, height: 54)
        case .thinking:  return CGSize(width: 200, height: 50)
        case .speaking:  return CGSize(width: 370, height: 60)
        case .alert:     return CGSize(width: 180, height: 46)
        }
    }

    /// Shadow radius (glow intensity) for this state
    var shadowRadius: CGFloat {
        switch self {
        case .idle:      return  8
        case .listening: return 12
        case .thinking:  return 10
        case .speaking:  return 14
        case .alert:     return 22
        }
    }

    /// Map a particle-system state string → NotchState
    static func fromParticleState(_ s: String) -> NotchState {
        switch s {
        case "listening": return .listening
        case "thinking":  return .thinking
        case "acting":    return .speaking
        case "error":     return .alert
        default:          return .idle
        }
    }
}

// MARK: - NotchStateManager ───────────────────────────────────────────────────
/// Thread-safe state store. Uses NotificationCenter for UI updates so there is
/// no SwiftUI dependency.  Always post from the main thread.
final class NotchStateManager {

    static let shared = NotchStateManager()

    /// Posted on DispatchQueue.main when the notch state changes.
    static let stateChangedNotification = Notification.Name("JarvisNotchStateChanged")

    /// Posted on DispatchQueue.main when a one-shot alert fires.
    static let alertFiredNotification   = Notification.Name("JarvisNotchAlertFired")

    // MARK: Published properties (read from main thread)
    private(set) var currentState:  NotchState = .idle
    private(set) var audioAmplitude: Float     = 0.5
    private(set) var alertMessage:  String     = ""

    private init() {}

    // MARK: - Mutations (thread-safe)

    func setState(_ state: NotchState, amplitude: Float = 0.5) {
        let work = {
            self.currentState   = state
            self.audioAmplitude = max(0, min(1, amplitude))
            NotificationCenter.default.post(
                name:   Self.stateChangedNotification,
                object: self
            )
        }
        if Thread.isMainThread { work() } else { DispatchQueue.main.async(execute: work) }
    }

    func triggerAlert(message: String) {
        let work = {
            self.alertMessage = message
            NotificationCenter.default.post(
                name:   Self.alertFiredNotification,
                object: self
            )
        }
        if Thread.isMainThread { work() } else { DispatchQueue.main.async(execute: work) }
    }
}

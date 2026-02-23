import Foundation
import simd

// ── Color palettes (same 4 states as Python overlay) ──────────────────────────

private let kPalettes: [String: (a: SIMD3<Float>, b: SIMD3<Float>)] = [
    "idle":      (a: [0.000, 1.000, 0.878], b: [0.482, 0.188, 1.000]),   // cyan + purple
    "listening": (a: [0.000, 1.000, 0.533], b: [0.000, 1.000, 0.878]),   // green + cyan
    "thinking":  (a: [1.000, 0.882, 0.000], b: [1.000, 0.549, 0.000]),   // yellow + orange
    "acting":    (a: [1.000, 0.125, 0.376], b: [0.545, 0.000, 1.000]),   // pink + purple
]

// ── GPU particle layout (must match MSL struct byte-for-byte) ─────────────────

struct GPUParticle {
    var x, y:       Float       //  0..7
    var r, g, b, a: Float       //  8..23
    var size:       Float       // 24..27
    var pad:        Float = 0   // 28..31  (alignment padding)
}   // 32 bytes total

// ── CPU-side particle (spring physics) ────────────────────────────────────────

private struct Particle {
    var x, y:         Float    // current position
    var vx, vy:       Float    // velocity
    var homeX, homeY: Float    // rest offset from cloud centre (sunflower spiral)
    var noisePhase:   Float    // individual noise seed
    var r, g, b:      Float    // current colour
    var alpha:        Float
    var size:         Float    // point radius
}

// ── Particle system ───────────────────────────────────────────────────────────

final class ParticleSystem {

    let count = 80

    private var ps:      [Particle]
    var         gpuData: [GPUParticle]

    private(set) var state: String = "idle"
    var centerX: Float
    var centerY: Float
    private var noiseT:   Float = 0
    private var audioMul: Float = 1.0   // expanded by set_audio_level

    // Spring constants
    private let baseR:    Float = 85.0
    private let springK:  Float = 4.8
    private let damping:  Float = 0.74
    private let noiseAmp: Float = 18.0

    // MARK: - Init

    init(centerX: Float, centerY: Float) {
        self.centerX = centerX
        self.centerY = centerY

        ps      = []
        gpuData = Array(
            repeating: GPUParticle(x: 0, y: 0, r: 0, g: 0, b: 0, a: 0, size: 0),
            count: 80
        )

        let golden: Float = 2.399_963   // golden angle (radians)
        let (ca, cb) = kPalettes["idle"]!

        for i in 0..<count {
            let fi    = Float(i)
            let angle = fi * golden
            let r     = baseR * sqrt(fi / Float(max(count - 1, 1)))
            let hx    = r * cos(angle)
            let hy    = r * sin(angle)
            let t     = fi / Float(count - 1)

            ps.append(Particle(
                x: centerX + hx,  y: centerY + hy,
                vx: 0, vy: 0,
                homeX: hx, homeY: hy,
                noisePhase: Float.random(in: 0 ..< .pi * 2),
                r: ca.x*(1-t) + cb.x*t,
                g: ca.y*(1-t) + cb.y*t,
                b: ca.z*(1-t) + cb.z*t,
                alpha: Float.random(in: 0.55...0.95),
                size:  Float.random(in: 2.0...4.5)
            ))
        }
    }

    // MARK: - Public API (mirrors Python bridge API)

    func setState(_ newState: String) {
        state = newState
        guard let (ca, cb) = kPalettes[newState] else { return }
        for i in 0..<count {
            let t = Float(i) / Float(count - 1)
            ps[i].r = ca.x*(1-t) + cb.x*t
            ps[i].g = ca.y*(1-t) + cb.y*t
            ps[i].b = ca.z*(1-t) + cb.z*t
        }
    }

    /// Expand the cloud when voice audio is detected (0.0–1.0)
    func setAudioLevel(_ level: Float) {
        audioMul = 1.0 + level * 1.8
    }

    // MARK: - Physics update (called every frame)

    func update(dt: Float) {
        noiseT += dt * 0.38

        for i in 0..<count {
            let phase = ps[i].noisePhase
            let mul   = noiseAmp * audioMul

            let nx = mul * sin(noiseT        + phase)
            let ny = mul * cos(noiseT * 1.27 + phase * 0.73)

            let tx = centerX + ps[i].homeX + nx
            let ty = centerY + ps[i].homeY + ny

            // Spring towards noisy home
            let fx = (tx - ps[i].x) * springK
            let fy = (ty - ps[i].y) * springK

            ps[i].vx = (ps[i].vx + fx * dt) * damping
            ps[i].vy = (ps[i].vy + fy * dt) * damping
            ps[i].x += ps[i].vx * dt
            ps[i].y += ps[i].vy * dt

            gpuData[i] = GPUParticle(
                x: ps[i].x, y: ps[i].y,
                r: ps[i].r, g: ps[i].g, b: ps[i].b, a: ps[i].alpha,
                size: ps[i].size
            )
        }

        // Decay audio expansion
        audioMul = max(1.0, audioMul - dt * 2.5)
    }
}

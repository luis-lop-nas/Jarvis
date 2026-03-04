import AppKit
import QuartzCore

// MARK: - NotchAnimationView ──────────────────────────────────────────────────
/// Transparent NSView placed at the top-center of the overlay window that
/// renders animated notch shapes using Core Animation.
///
/// Coordinate note:  AppKit and macOS Core Animation both use a bottom-left
/// origin with Y increasing upward.  The view's frame is positioned so that
/// its top edge (y = frame.maxY) coincides with the top of the screen.
/// The pill shape is therefore drawn at the TOP of the view bounds (large Y).
///
/// Usage:
///   let notch = NotchAnimationView(screen: NSScreen.main!)
///   metalView.addSubview(notch)
///   notch.setState(.listening, amplitude: 0.7)
///   notch.triggerAlert(message: "Done")
final class NotchAnimationView: NSView {

    // ── Container geometry ───────────────────────────────────────────────────
    /// Width of this view (fits the widest pill state with room for glow)
    private static let viewWidth:  CGFloat = 440
    /// Height of this view (pill height + glow room below)
    private static let viewHeight: CGFloat = 90

    // ── Sub-layers ───────────────────────────────────────────────────────────
    /// Black pill shape with coloured glow shadow
    private let shapeLyr  = CAShapeLayer()
    /// Waveform stroke inside the pill (listening / speaking)
    private let waveLyr   = CAShapeLayer()
    /// 4 small dots orbiting the pill in thinking state
    private var orbitDots = [CALayer]()

    // ── Animation state ──────────────────────────────────────────────────────
    private(set) var currentState:  NotchState = .idle
    private var audioAmplitude: Float          = 0.5
    private var wavePhase:      Double    = 0
    private var waveTimer:      Timer?

    // MARK: - Init ─────────────────────────────────────────────────────────────

    /// Preferred factory: positions the view correctly relative to `screen`.
    convenience init(screen: NSScreen) {
        let sw = screen.frame.width
        let sh = screen.frame.height
        let frame = NSRect(
            x:      (sw - Self.viewWidth) / 2,
            y:       sh - Self.viewHeight,          // top of view = top of screen
            width:  Self.viewWidth,
            height: Self.viewHeight
        )
        self.init(frame: frame)
    }

    override init(frame: NSRect) {
        super.init(frame: frame)
        commonInit()
    }

    required init?(coder: NSCoder) {
        super.init(coder: coder)
        commonInit()
    }

    private func commonInit() {
        wantsLayer              = true
        layer?.backgroundColor  = .clear

        setupShapeLayer()
        setupWaveLayer()
        setupOrbitDots()

        // Start in idle state silently
        applyShape(for: .idle, animated: false)
        startIdleBreathing()

        // Listen to state-change notifications from NotchStateManager
        NotificationCenter.default.addObserver(
            self,
            selector: #selector(handleStateChanged(_:)),
            name:     NotchStateManager.stateChangedNotification,
            object:   nil
        )
        NotificationCenter.default.addObserver(
            self,
            selector: #selector(handleAlert(_:)),
            name:     NotchStateManager.alertFiredNotification,
            object:   nil
        )
    }

    deinit {
        waveTimer?.invalidate()
        NotificationCenter.default.removeObserver(self)
    }

    // MARK: - Layer setup ──────────────────────────────────────────────────────

    private func setupShapeLayer() {
        shapeLyr.fillColor    = NSColor.black.cgColor
        // Glow via shadow (shadowOffset = zero → uniform halo)
        shapeLyr.shadowOffset  = .zero
        shapeLyr.shadowOpacity = 0.85
        shapeLyr.shadowRadius  = NotchState.idle.shadowRadius
        shapeLyr.shadowColor   = NotchState.idle.accentColor.cgColor
        // Grow the shadow bounds beyond the shape
        shapeLyr.masksToBounds = false
        layer!.addSublayer(shapeLyr)
    }

    private func setupWaveLayer() {
        waveLyr.fillColor   = nil
        waveLyr.strokeColor = NotchState.idle.accentColor.cgColor
        waveLyr.lineWidth   = 2.0
        waveLyr.lineCap     = .round
        waveLyr.opacity     = 0
        waveLyr.masksToBounds = false
        layer!.addSublayer(waveLyr)
    }

    private func setupOrbitDots() {
        let colors: [NSColor] = [
            NotchState.thinking.accentColor,
            NotchState.thinking.glowColor,
            NotchState.thinking.accentColor.withAlphaComponent(0.6),
            NotchState.thinking.glowColor.withAlphaComponent(0.6),
        ]
        for color in colors {
            let dot = CALayer()
            dot.bounds        = CGRect(x: 0, y: 0, width: 7, height: 7)
            dot.cornerRadius  = 3.5
            dot.backgroundColor = color.cgColor
            dot.opacity       = 0
            dot.shadowColor   = color.cgColor
            dot.shadowRadius  = 4
            dot.shadowOpacity = 0.8
            dot.shadowOffset  = .zero
            layer!.addSublayer(dot)
            orbitDots.append(dot)
        }
    }

    // MARK: - Public API ───────────────────────────────────────────────────────

    /// Transition to a new state with spring-like morphing animation.
    func setState(_ state: NotchState, amplitude: Float = 0.5) {
        // Always update amplitude so tickWave() picks it up immediately
        audioAmplitude = max(0, min(1, amplitude))
        guard state != currentState else { return }

        let previous = currentState
        currentState = state

        stopAllStateAnimations()
        applyShape(for: state, animated: true)
        startAnimations(for: state, previous: previous)
    }

    /// Trigger a one-shot bounce+glow alert, then return to idle after 3 s.
    func triggerAlert(message: String) {
        currentState = .alert
        stopAllStateAnimations()
        applyShape(for: .alert, animated: true)
        playAlertAnimation()

        DispatchQueue.main.asyncAfter(deadline: .now() + 3.0) { [weak self] in
            self?.setState(.idle)
        }
    }

    // MARK: - Notification handlers ────────────────────────────────────────────

    @objc private func handleStateChanged(_ note: Notification) {
        guard let mgr = note.object as? NotchStateManager else { return }
        setState(mgr.currentState, amplitude: mgr.audioAmplitude)
    }

    @objc private func handleAlert(_ note: Notification) {
        guard let mgr = note.object as? NotchStateManager else { return }
        triggerAlert(message: mgr.alertMessage)
    }

    // MARK: - Shape application ────────────────────────────────────────────────

    /// Build the pill CGPath centred in bounds, top-aligned (flush with screen top).
    private func pillPath(for state: NotchState) -> CGPath {
        let size   = state.pillSize
        let rect   = CGRect(
            x:      (bounds.width  - size.width)  / 2,
            y:       bounds.height - size.height,  // top of pill = top of view
            width:  size.width,
            height: size.height
        )
        let radius = size.height / 2
        return CGPath(roundedRect: rect, cornerWidth: radius, cornerHeight: radius,
                      transform: nil)
    }

    private func applyShape(for state: NotchState, animated: Bool) {
        let newPath    = pillPath(for: state)
        let newShadow  = state.glowColor.cgColor
        let newRadius  = state.shadowRadius

        if animated {
            // Path morph with spring-like cubic bezier timing
            let pathAnim            = CABasicAnimation(keyPath: "path")
            pathAnim.fromValue      = shapeLyr.presentation()?.path ?? shapeLyr.path
            pathAnim.toValue        = newPath
            pathAnim.duration       = 0.55
            // Approximate spring: fast approach, slight overshoot, settle
            pathAnim.timingFunction = CAMediaTimingFunction(
                controlPoints: 0.34, 1.5, 0.64, 1.0
            )
            shapeLyr.add(pathAnim, forKey: "morphPath")

            let shadowAnim          = CABasicAnimation(keyPath: "shadowColor")
            shadowAnim.fromValue    = shapeLyr.presentation()?.shadowColor ?? shapeLyr.shadowColor
            shadowAnim.toValue      = newShadow
            shadowAnim.duration     = 0.4
            shapeLyr.add(shadowAnim, forKey: "shadowColor")

            let radAnim             = CABasicAnimation(keyPath: "shadowRadius")
            radAnim.fromValue       = shapeLyr.presentation()?.shadowRadius ?? shapeLyr.shadowRadius
            radAnim.toValue         = newRadius
            radAnim.duration        = 0.4
            shapeLyr.add(radAnim, forKey: "shadowRadius")
        }

        // Commit model values (Core Animation uses these after animation ends)
        CATransaction.begin()
        CATransaction.setDisableActions(true)
        shapeLyr.path         = newPath
        shapeLyr.shadowColor  = newShadow
        shapeLyr.shadowRadius = newRadius
        CATransaction.commit()

        // Sync wave stroke colour
        waveLyr.strokeColor = state.accentColor.cgColor
    }

    // MARK: - Per-state animations ─────────────────────────────────────────────

    private func stopAllStateAnimations() {
        waveTimer?.invalidate()
        waveTimer = nil

        shapeLyr.removeAnimation(forKey: "breathing")
        shapeLyr.removeAnimation(forKey: "bounce")
        shapeLyr.removeAnimation(forKey: "alertFlash")

        CATransaction.begin()
        CATransaction.setDisableActions(true)
        waveLyr.opacity = 0
        orbitDots.forEach { $0.opacity = 0; $0.removeAllAnimations() }
        CATransaction.commit()
    }

    private func startAnimations(for state: NotchState, previous: NotchState) {
        switch state {
        case .idle:      startIdleBreathing()
        case .listening: startWave(speed: 0.06)
        case .thinking:  startOrbitDots()
        case .speaking:  startWave(speed: 0.10)
        case .alert:     break  // handled by triggerAlert
        }
    }

    // ── Idle: gentle glow pulse ───────────────────────────────────────────────
    private func startIdleBreathing() {
        let pulse            = CABasicAnimation(keyPath: "shadowRadius")
        pulse.fromValue      = 5.0
        pulse.toValue        = 14.0
        pulse.duration       = 2.8
        pulse.autoreverses   = true
        pulse.repeatCount    = .infinity
        pulse.timingFunction = CAMediaTimingFunction(name: .easeInEaseOut)
        shapeLyr.add(pulse, forKey: "breathing")
    }

    // ── Listening / Speaking: animated waveform ───────────────────────────────
    private func startWave(speed: Double) {
        CATransaction.begin()
        CATransaction.setDisableActions(true)
        waveLyr.opacity = 1
        CATransaction.commit()

        wavePhase = 0
        waveTimer = Timer.scheduledTimer(withTimeInterval: 1.0 / 60.0, repeats: true) {
            [weak self] _ in self?.tickWave(speed: speed)
        }
    }

    private func tickWave(speed: Double) {
        wavePhase += speed

        let size      = currentState.pillSize
        let waveW     = size.width  - 20          // horizontal margin inside pill
        let halfH     = (size.height * 0.40) / 2  // max amplitude half-height
        let amp       = CGFloat(audioAmplitude) * halfH

        // Pill centre in view coordinates (Y-up)
        let cx  = bounds.midX
        let cy  = bounds.height - size.height / 2  // centre of pill

        let path   = CGMutablePath()
        let steps  = 80

        for j in 0 ... steps {
            let t:  CGFloat = CGFloat(j) / CGFloat(steps)
            let x   = cx - waveW / 2 + t * waveW
            // Multi-harmonic for an organic, non-mechanical look
            let y   = cy
                + amp * 0.55 * CGFloat(sin(wavePhase         + Double(t) * .pi * 4))
                + amp * 0.30 * CGFloat(sin(wavePhase * 1.73  + Double(t) * .pi * 7))
                + amp * 0.15 * CGFloat(sin(wavePhase * 2.37  + Double(t) * .pi * 11))

            if j == 0 { path.move(to: CGPoint(x: x, y: y)) }
            else       { path.addLine(to: CGPoint(x: x, y: y)) }
        }

        CATransaction.begin()
        CATransaction.setDisableActions(true)
        waveLyr.path = path
        CATransaction.commit()
    }

    // ── Thinking: 4 dots orbiting the pill ────────────────────────────────────
    private func startOrbitDots() {
        let pillSize  = NotchState.thinking.pillSize
        let centerX   = bounds.midX
        let centerY   = bounds.height - pillSize.height / 2  // pill centre Y
        let orbitR    = pillSize.height / 2 + 12             // just outside pill

        // Orbit ellipse path (wider than tall — hugs the pill)
        let orbitRect = CGRect(
            x:      centerX - (pillSize.width / 2 + 14),
            y:      centerY - orbitR,
            width:  pillSize.width + 28,
            height: orbitR * 2
        )
        let orbitPath = CGPath(ellipseIn: orbitRect, transform: nil)

        for (i, dot) in orbitDots.enumerated() {
            CATransaction.begin()
            CATransaction.setDisableActions(true)
            dot.opacity = 0.85
            dot.position = CGPoint(x: centerX, y: centerY + orbitR)
            CATransaction.commit()

            let anim              = CAKeyframeAnimation(keyPath: "position")
            anim.path             = orbitPath
            anim.duration         = 2.4
            anim.repeatCount      = .infinity
            anim.calculationMode  = .paced
            // Stagger each dot by 1/4 of the orbit period
            anim.timeOffset       = anim.duration / Double(orbitDots.count) * Double(i)
            dot.add(anim, forKey: "orbit")
        }
    }

    // ── Alert: bounce + flash ─────────────────────────────────────────────────
    private func playAlertAnimation() {
        // Vertical bounce of the shape layer's position within the view
        let baseY   = shapeLyr.position.y
        let bounce  = CAKeyframeAnimation(keyPath: "position.y")
        bounce.values   = [baseY, baseY + 9, baseY - 4, baseY + 2, baseY]
        bounce.keyTimes = [0.0, 0.22, 0.55, 0.78, 1.0]
        bounce.duration = 0.45
        bounce.repeatCount = 2
        bounce.timingFunction = CAMediaTimingFunction(name: .easeOut)
        shapeLyr.add(bounce, forKey: "bounce")

        // Shadow radius flash
        let flash         = CABasicAnimation(keyPath: "shadowRadius")
        flash.fromValue   = shapeLyr.shadowRadius
        flash.toValue     = 28.0
        flash.duration    = 0.14
        flash.autoreverses = true
        flash.repeatCount  = 4
        shapeLyr.add(flash, forKey: "alertFlash")
    }
}

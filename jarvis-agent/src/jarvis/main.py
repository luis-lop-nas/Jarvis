"""
main.py

Entry point del proyecto.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

from jarvis.config import load_settings
from jarvis.logging_setup import setup_logging


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="jarvis", description="Jarvis Agent (CLI + Voice + Web + Desktop)")
    p.add_argument(
        "--voice",
        action="store_true",
        help="Activa modo voz + wake word.",
    )
    p.add_argument(
        "--web",
        action="store_true",
        help="Activa servidor web (interface gráfica).",
    )
    p.add_argument(
        "--desktop",
        action="store_true",
        help="Activa modo escritorio: overlay visual + voz + LLM (macOS).",
    )
    p.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Puerto para servidor web (default: 8000).",
    )
    p.add_argument(
        "--no-voice",
        action="store_true",
        help="Fuerza modo solo-CLI.",
    )
    p.add_argument(
        "--debug",
        action="store_true",
        help="Activa modo debug.",
    )
    p.add_argument(
        "--install-autostart",
        action="store_true",
        help="Instala autoarranque de Jarvis Desktop al iniciar sesión (macOS).",
    )
    p.add_argument(
        "--uninstall-autostart",
        action="store_true",
        help="Desinstala autoarranque de Jarvis Desktop (macOS).",
    )
    p.add_argument(
        "--autostart-status",
        action="store_true",
        help="Muestra estado del autoarranque de Jarvis Desktop (macOS).",
    )
    p.add_argument(
        "--restart-autostart",
        action="store_true",
        help="Reinicia (reinstala) autoarranque de Jarvis Desktop (macOS).",
    )
    p.add_argument(
        "--doctor-desktop",
        action="store_true",
        help="Diagnóstico de estado desktop (autoarranque/permisos) en macOS.",
    )
    p.add_argument(
        "--class-session",
        action="store_true",
        help="Graba una clase, transcribe, resume y extrae tareas académicas.",
    )
    p.add_argument(
        "--class-seconds",
        type=float,
        default=180.0,
        help="Duración de grabación para --class-session (segundos).",
    )
    p.add_argument(
        "--class-title",
        type=str,
        default="",
        help="Título opcional para identificar la sesión de clase.",
    )
    p.add_argument(
        "--class-audio",
        type=str,
        default="",
        help="Ruta a WAV existente para procesar en --class-session (sin grabar).",
    )
    p.add_argument(
        "--no-class-calendar-sync",
        action="store_true",
        help="No crear recordatorios de calendario al procesar --class-session.",
    )
    return p


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    settings, paths = load_settings()

    if args.debug:
        settings.debug = True  # type: ignore[attr-defined]

    # Configurar logging estructurado con rotación (10 MB × 5 ficheros)
    setup_logging(debug=bool(settings.debug), logs_dir=paths.logs_dir)

    if args.install_autostart:
        from jarvis.desktop.autostart import install_launch_agent

        ok, msg, plist = install_launch_agent(
            project_root=paths.project_root,
            logs_dir=paths.logs_dir,
        )
        print(msg)
        print(f"plist: {plist}")
        return 0 if ok else 1

    if args.uninstall_autostart:
        from jarvis.desktop.autostart import uninstall_launch_agent

        ok, msg, plist = uninstall_launch_agent()
        print(msg)
        print(f"plist: {plist}")
        return 0 if ok else 1

    if args.autostart_status:
        from jarvis.desktop.autostart import get_autostart_status

        st = get_autostart_status()
        print(f"label: {st.label}")
        print(f"installed: {st.installed}")
        print(f"loaded: {st.loaded}")
        print(f"plist: {st.plist_path}")
        if st.error:
            print(f"detail: {st.error}")
        return 0

    if args.restart_autostart:
        from jarvis.desktop.autostart import restart_launch_agent

        ok, msg, plist = restart_launch_agent(
            project_root=paths.project_root,
            logs_dir=paths.logs_dir,
        )
        print(msg)
        print(f"plist: {plist}")
        return 0 if ok else 1

    if args.doctor_desktop:
        from jarvis.desktop.doctor import doctor_result_to_dict, run_desktop_doctor

        report = doctor_result_to_dict(run_desktop_doctor(attempt_repair=True))
        print(f"platform: {report['platform']}")
        print(f"autostart_installed: {report['autostart_installed']}")
        print(f"autostart_loaded: {report['autostart_loaded']}")
        print(f"microphone: {report['microphone']}")
        print(f"accessibility: {report['accessibility']}")
        if report["issues"]:
            print("issues:")
            for issue in report["issues"]:
                print(f"- {issue}")
        else:
            print("issues: none")
        return 0 if report["ok"] else 1

    if args.class_session:
        from jarvis.intents.class_session import process_class_session

        audio_path = Path(args.class_audio).expanduser() if args.class_audio else None
        result = process_class_session(
            settings=settings,
            seconds=args.class_seconds,
            class_title=args.class_title or None,
            audio_path=audio_path,
            sync_calendar=not args.no_class_calendar_sync,
        )

        print("Transcripción:")
        print(result.transcript or "(vacía)")
        print("\nResumen:")
        print(result.summary or "(sin resumen)")
        print("\nTareas detectadas:")
        if not result.tasks:
            print("- Ninguna")
        else:
            for task in result.tasks:
                when = ""
                if task.due_date and task.due_time:
                    when = f" ({task.due_date} {task.due_time})"
                elif task.due_date:
                    when = f" ({task.due_date})"
                print(f"- {task.title}{when}")
        print(f"\nRecordatorios creados: {result.calendar_created}")
        print(f"Transcripción guardada en: {result.transcript_path}")
        return 0

    # Modo DESKTOP (macOS overlay + voz + LLM)
    if args.desktop:
        _run_desktop(settings, paths)
        return 0

    # Modo WEB
    if args.web:
        import uvicorn
        from jarvis.web.server import app
        
        print(f"🌐 Iniciando servidor web en http://localhost:{args.port}")
        print(f"   Abre tu navegador y ve a: http://localhost:{args.port}")
        print("   Presiona Ctrl+C para detener\n")
        
        uvicorn.run(
            app,
            host="0.0.0.0",
            port=args.port,
            log_level="info"
        )
        return 0

    # Modo VOZ
    use_voice = False
    if args.no_voice:
        use_voice = False
    elif args.voice:
        use_voice = True

    try:
        if use_voice:
            from jarvis.voice.voice_loop import VoiceLoop
            from jarvis.voice.wake_word import WakeWordConfig
            from jarvis.voice.stt import STTConfig
            from jarvis.voice.tts import TTSConfig
            from jarvis.agent.tool_agent import tool_agent_from_settings
            from jarvis.memory.store import MemoryStore

            memory_store = MemoryStore(paths.db_path)
            agent = tool_agent_from_settings(settings, memory_store=memory_store, paths=paths)

            wake_cfg = WakeWordConfig(
                engine=settings.wake_word_engine,
                oww_model=settings.wake_word_model,
                sensitivity=settings.wake_word_sensitivity,
                device_index=settings.wake_word_device,
                debug=settings.wake_word_debug,
                oww_min_rms=settings.wake_word_min_rms,
                oww_min_consecutive_hits=settings.wake_word_min_hits,
                oww_activation_cooldown_sec=settings.wake_word_cooldown,
                oww_score_ema_alpha=settings.wake_word_score_ema_alpha,
                access_key=settings.porcupine_access_key,
                keyword=settings.wake_word,
            )

            stt_cfg = STTConfig(
                engine=settings.stt_engine,
                groq_api_key=settings.groq_api_key,
                groq_model=settings.stt_groq_model,
                whisper_model=settings.stt_whisper_model,
            )
            tts_cfg = TTSConfig(
                engine=settings.tts_engine,
                kokoro_voice=settings.kokoro_voice,
                kokoro_speed=settings.kokoro_speed,
                kokoro_language=settings.kokoro_language,
            )

            voice_loop = VoiceLoop(
                wake_cfg=wake_cfg,
                stt_cfg=stt_cfg,
                tts_cfg=tts_cfg,
            )

            print("🎤 Modo voz activado. Di 'Jarvis' para activar...")
            print("Presiona Ctrl+C para salir.\n")

            def agent_fn(text: str) -> str:
                txt = (text or "").strip().lower()
                if "buenos días" in txt or "buenos dias" in txt:
                    from jarvis.intents.good_morning import run_morning_briefing

                    return run_morning_briefing().text
                return agent.run(text)

            voice_loop.run_forever(agent_fn)
        else:
            # Modo CLI
            from jarvis.ui.cli import run_cli
            run_cli(settings=settings, paths=paths)
    except KeyboardInterrupt:
        print("\n👋 Hasta luego!")

    return 0


def _run_desktop(settings, paths) -> None:
    """Arranca Jarvis en modo escritorio: overlay NSWindow + daemon voz/LLM."""
    try:
        import Quartz
        session = Quartz.CGSessionCopyCurrentDictionary()
    except Exception:
        session = None

    if not session:
        print("⚠️ No hay una sesión gráfica activa de macOS para iniciar el overlay desktop.")
        print("   Inicia sesión en el escritorio (no solo terminal remota) y vuelve a ejecutar --desktop.")
        return

    import signal
    import AppKit

    from jarvis.overlay.window     import JarvisWindow
    from jarvis.overlay.view       import JarvisView
    from jarvis.overlay.bridge     import OverlayBridge
    from jarvis.overlay.particles  import ParticleSystem
    from jarvis.overlay.daemon     import JarvisDaemon
    from jarvis.overlay.menubar    import MenuBar
    from jarvis.overlay.chat_panel import ChatPanel
    from jarvis.overlay.main_panel import MainPanel

    signal.signal(
        signal.SIGINT,
        lambda *_: AppKit.NSApplication.sharedApplication().terminate_(None),
    )

    app = AppKit.NSApplication.sharedApplication()
    app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)

    screen = AppKit.NSScreen.mainScreen()
    frame  = screen.frame()
    sw, sh = frame.size.width, frame.size.height

    # ── Overlay visual (oculto — Jarvis vive en el notch) ─────────────────────
    view      = JarvisView.alloc().initWithFrame_(frame)
    _window   = JarvisWindow(view)
    _window.win.orderOut_(None)   # esconder el orb de abajo-izquierda

    particles = ParticleSystem(view)
    view.attach_particles(particles)

    bridge = OverlayBridge()
    bridge.attach(view, particles)

    # ── Daemon (voz + LLM + tools) ────────────────────────────────────────────
    daemon = JarvisDaemon(bridge, sw, sh, settings, paths)

    # Conectar HUD al view para sincronizar color de borde con el estado
    view.set_hud(daemon._hud)

    # ── Barra de menú ─────────────────────────────────────────────────────────
    _menubar = MenuBar(daemon)

    # ── Panel de chat ──────────────────────────────────────────────────────────
    _chat_panel = ChatPanel(bridge, daemon)
    daemon.set_chat_panel(_chat_panel)

    # ── Panel principal (liquid glass) ────────────────────────────────────────
    _main_panel = MainPanel(bridge, daemon, _chat_panel)

    # Conectar panel al menú de la barra de menú
    _menubar.set_main_panel(_main_panel)

    # ── Notch digital (visualizador principal) ────────────────────────────────
    from jarvis.overlay.notch_panel import NotchPanel
    _notch_panel = NotchPanel()
    bridge.attach_notch(_notch_panel)

    # ── Annotation overlay (opcional — solo si está habilitado en config) ────
    _ann_overlay = None
    if getattr(settings, "annotation_overlay_enabled", True):
        try:
            from jarvis.overlay import annotation as _ann_mod
            _ann_overlay = _ann_mod.AnnotationOverlay()
            _ann_mod.set_instance(_ann_overlay)
        except Exception as _e:
            print(f"⚠️ Annotation overlay no disponible: {_e}")

    # ── Gesture controller (opcional) ─────────────────────────────────────────
    _gesture_ctrl = None
    if getattr(settings, "use_gestures", False):
        from jarvis.vision.gesture_controller import build_gesture_controller
        _gesture_ctrl = build_gesture_controller(settings, daemon)

    # ── Vision Monitor (ventana de debug de cámara) ────────────────────────────
    _vision_monitor = None
    try:
        from jarvis.overlay.vision_monitor import VisionMonitor
        _vision_monitor = VisionMonitor(
            camera_index=getattr(settings, "gesture_camera_index", 0)
        )
    except Exception as _e:
        print(f"⚠️ Vision Monitor no disponible: {_e}")

    # ── App delegate — definido DESPUÉS de todos los componentes ──────────────
    class _AppDelegate(AppKit.NSObject):

        def applicationDidFinishLaunching_(self, notification) -> None:
            daemon.start()
            if _gesture_ctrl is not None:
                _gesture_ctrl.start()
            if _vision_monitor is not None:
                _vision_monitor.start(
                    gesture_ctrl=_gesture_ctrl,
                    camera_ctx=daemon._camera_ctx,
                )

        def applicationShouldHandleReopen_hasVisibleWindows_(self, sender, flag) -> bool:
            """Clic en el acceso directo del escritorio → toggle del panel."""
            _main_panel.toggle_on_main()
            return False

    _delegate = _AppDelegate.alloc().init()
    app.setDelegate_(_delegate)

    print("\n🔵 Jarvis Desktop activo.")
    print(f"   Pantalla: {int(sw)}×{int(sh)}")
    print("   Di «Hey Jarvis» o pulsa Ctrl+Space para hablar.")
    print("   Haz clic en el orb o en el acceso directo para abrir el panel.\n")

    # NSApplication runloop — bloquea hasta Cmd+Q / Salir
    app.run()

    daemon.stop()
    if _gesture_ctrl is not None:
        _gesture_ctrl.stop()
    if _vision_monitor is not None:
        _vision_monitor.stop()


if __name__ == "__main__":
    raise SystemExit(main())

"""
main.py

Entry point del proyecto.
"""

from __future__ import annotations

import argparse
from typing import Optional

from jarvis.config import load_settings


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
    return p


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    settings, paths = load_settings()

    if args.debug:
        settings.debug = True  # type: ignore[attr-defined]

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

    if use_voice:
        from jarvis.voice.voice_loop import VoiceLoop
        from jarvis.voice.wake_word import WakeWordConfig
        from jarvis.voice.stt import STTConfig
        from jarvis.voice.tts import TTSConfig
        from jarvis.agent.tool_agent import tool_agent_from_settings
        from jarvis.memory.store import MemoryStore

        memory_store = MemoryStore(paths.db_path)
        agent = tool_agent_from_settings(settings, memory_store=memory_store)

        wake_cfg = WakeWordConfig(
            engine=settings.wake_word_engine,
            oww_model=settings.wake_word_model,
            sensitivity=settings.wake_word_sensitivity,
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
            elevenlabs_api_key=settings.elevenlabs_api_key,
            elevenlabs_voice_id=settings.elevenlabs_voice_id,
            elevenlabs_model=settings.elevenlabs_model,
        )

        voice_loop = VoiceLoop(
            wake_cfg=wake_cfg,
            stt_cfg=stt_cfg,
            tts_cfg=tts_cfg,
        )

        print("🎤 Modo voz activado. Di 'Jarvis' para activar...")
        print("Presiona Ctrl+C para salir.\n")

        def agent_fn(text: str) -> str:
            return agent.run(text)

        voice_loop.run_forever(agent_fn)
    else:
        # Modo CLI
        from jarvis.ui.cli import run_cli
        run_cli(settings=settings, paths=paths)

    return 0


def _run_desktop(settings, paths) -> None:
    """Arranca Jarvis en modo escritorio: overlay NSWindow + daemon voz/LLM."""
    import signal
    import objc
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

    # ── Overlay visual ────────────────────────────────────────────────────────
    view      = JarvisView.alloc().initWithFrame_(frame)
    _window   = JarvisWindow(view)

    particles = ParticleSystem(view)
    view.attach_particles(particles)

    bridge = OverlayBridge()
    bridge.attach(view, particles)

    # ── Daemon (voz + LLM + tools) ────────────────────────────────────────────
    daemon = JarvisDaemon(bridge, sw, sh, settings, paths)
    daemon.start()

    # ── Barra de menú ─────────────────────────────────────────────────────────
    _menubar = MenuBar(daemon)

    # ── Panel de chat ──────────────────────────────────────────────────────────
    _chat_panel = ChatPanel(bridge, daemon)
    daemon.set_chat_panel(_chat_panel)

    # ── Panel principal (liquid glass) ────────────────────────────────────────
    _main_panel = MainPanel(bridge, daemon, _chat_panel)

    # Conectar panel al menú de la barra de menú
    _menubar.set_main_panel(_main_panel)

    # ── App delegate — definido DESPUÉS de todos los componentes ──────────────
    class _AppDelegate(AppKit.NSObject):

        def applicationDidFinishLaunching_(self, notification) -> None:
            pass  # El panel se abre solo con el acceso directo (Ctrl+Space / Dock)

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


if __name__ == "__main__":
    raise SystemExit(main())

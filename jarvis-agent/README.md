# Jarvis

## Run Desktop

```bash
cd /Users/luichi/Documents/Jarvis/jarvis-agent
source .venv/bin/activate
PYTHONPATH=src python -m jarvis --desktop
```

## Auto-Start on Login (macOS)

```bash
cd /Users/luichi/Documents/Jarvis/jarvis-agent
source .venv/bin/activate
PYTHONPATH=src python -m jarvis --install-autostart
```

Check status:

```bash
PYTHONPATH=src python -m jarvis --autostart-status
```

Remove auto-start:

```bash
PYTHONPATH=src python -m jarvis --uninstall-autostart
```

Restart auto-start:

```bash
PYTHONPATH=src python -m jarvis --restart-autostart
```

Desktop doctor (permissions + autostart):

```bash
PYTHONPATH=src python -m jarvis --doctor-desktop
```

## Run Web

```bash
cd /Users/luichi/Documents/Jarvis/jarvis-agent
source .venv/bin/activate
PYTHONPATH=src uvicorn jarvis.web.server:app --host 0.0.0.0 --port 8000
```

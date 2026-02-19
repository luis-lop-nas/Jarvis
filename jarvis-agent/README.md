# Jarvis

## Run Desktop

```bash
cd /Users/luichi/Documents/Jarvis/jarvis-agent
source .venv/bin/activate
PYTHONPATH=src python -m jarvis --desktop
```

## Run Web

```bash
cd /Users/luichi/Documents/Jarvis/jarvis-agent
source .venv/bin/activate
PYTHONPATH=src uvicorn jarvis.web.server:app --host 0.0.0.0 --port 8000
```
# AGENT Instructions for HostBot Repository

This repository contains a Discord bot script (`hostbot.py`) that automates Zoom host management.

## Development Guidelines
- Use **Python 3.8+**.
- Keep code self‑contained; avoid unnecessary dependencies.
- Follow PEP8 style. Format code using `black` with line length **100**.
- Document new functions with docstrings.

## Programmatic Checks
For any Python code changes, ensure the script compiles:

```bash
python -m py_compile hostbot.py
```

Commit only after this command succeeds.


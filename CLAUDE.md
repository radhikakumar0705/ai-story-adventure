# CLAUDE.md: Echoes of Fate

AI story adventure game (college Gen-AI game prototype assignment). Flask back end, vanilla JS front end, an LLM narrator via an OpenAI-compatible API.

## Layout
- `app.py`: Flask routes (`/api/new`, `/api/act`, `/api/status`, `/api/transcript/<id>`) and JSON error handlers
- `game.py`: game rules: input validation, d20 risk rolls, effect clamping, endings, in-memory `GameStore`
- `ai_engine.py`: `StoryAI` client (presets: gemini, groq, openai, ollama), prompt builders, `extract_json`/`validate_*`, `OfflineNarrator` fallback
- `templates/index.html`, `static/game.js`, `static/style.css`: UI. Always render AI text with `textContent`.
- `tests/test_game.py`: pytest suite with a `FakeAI`; no key needed

## Commands
- Run: `python app.py` → http://127.0.0.1:5000 (config in `.env`, see `.env.example`)
- Test: `python -m pytest -q`

## Rules
- The AI only *proposes* effects; `game.py` clamps them (`OUTCOME_RANGES`). Keep that invariant.
- Any new AI output field must be validated in `ai_engine.validate_*` and have an offline fallback.
- Never commit `.env`.

"""
app.py - Flask web server for "Echoes of Fate", an AI story adventure.

Run:  python app.py      then open http://127.0.0.1:5000
"""

import logging
import os

from dotenv import load_dotenv
from flask import Flask, Response, jsonify, render_template, request

load_dotenv()

from ai_engine import StoryAI                     # noqa: E402  (needs env loaded first)
from game import (ARCHETYPES, SETTING_PRESETS, Game, GameStore, InvalidInput,  # noqa: E402
                  clean_archetype, clean_name, clean_setting)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024      # reject oversized requests
ai = StoryAI()
store = GameStore()

if ai.enabled:
    log.info("AI narrator: %s / %s", ai.provider, ai.model)
else:
    log.warning("AI narrator disabled (%s) - running with the OFFLINE backup narrator. "
                "Copy .env.example to .env and add an API key to enable Generative AI.", ai.disabled_reason)


@app.get("/")
def index():
    return render_template("index.html", archetypes=ARCHETYPES, settings=SETTING_PRESETS)


@app.get("/api/status")
def status():
    return jsonify(ai.describe())


@app.post("/api/new")
def new_game():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise InvalidInput("Request body must be JSON.")
    hero = clean_name(body.get("hero"))
    archetype = clean_archetype(body.get("archetype"))
    setting = clean_setting(body.get("setting"), body.get("custom_setting"))
    game = Game(ai, hero, archetype, setting)
    game.start()
    store.add(game)
    return jsonify(game.to_public())


@app.post("/api/act")
def act():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise InvalidInput("Request body must be JSON.")
    game = store.get(body.get("game_id"))
    if not game.lock.acquire(blocking=False):
        return jsonify(error="The narrator is still writing - wait for the current scene."), 409
    try:
        game.act(choice_index=body.get("choice"), custom_action=body.get("custom_action"))
    finally:
        game.lock.release()
    return jsonify(game.to_public())


@app.get("/api/transcript/<game_id>")
def transcript(game_id):
    game = store.get(game_id)
    name = "".join(c for c in game.story_title if c.isalnum() or c in " -_").strip().replace(" ", "_") or "story"
    return Response(game.transcript(), mimetype="text/plain",
                    headers={"Content-Disposition": f'attachment; filename="{name}.txt"'})


# ---- error handling: always answer the browser with friendly JSON ----------
@app.errorhandler(InvalidInput)
def bad_input(e):
    return jsonify(error=str(e)), 400


@app.errorhandler(413)
def too_large(_e):
    return jsonify(error="Request too large."), 413


@app.errorhandler(404)
def not_found(_e):
    if request.path.startswith("/api/"):
        return jsonify(error="Unknown endpoint."), 404
    return "Not found", 404


@app.errorhandler(Exception)
def unexpected(e):
    log.exception("Unexpected error")
    code = getattr(e, "code", 500)
    if not isinstance(code, int):
        code = 500
    return jsonify(error="Something went wrong on our side. Please try again."), code


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    print(f"\n  Echoes of Fate is running ->  http://127.0.0.1:{port}\n")
    app.run(host="127.0.0.1", port=port, debug=False)

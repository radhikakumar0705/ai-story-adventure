"""
game.py - game rules for "Echoes of Fate".

The AI writes the story; this module enforces the *game*:
  * input validation for names / settings / typed actions
  * a d20 dice roll per action, scaled by risk  -> SUCCESS / PARTIAL / FAILURE
  * clamping the AI's proposed effects to fair ranges for that outcome
  * health, quest progress, inventory and turn limit
  * deciding when and how the game ends (victory / defeat / bittersweet / lost)
"""

from __future__ import annotations

import random
import re
import threading
import time
import uuid

from ai_engine import (AIError, OfflineNarrator, StoryAI, SYSTEM_PROMPT,
                       build_ending_prompt, build_opening_prompt, build_turn_prompt,
                       validate_ending, validate_scene)

MAX_TURNS = 10
MAX_INVENTORY = 6

# d20 thresholds per risk: (min roll for SUCCESS, min roll for PARTIAL)
RISK_TABLE = {"low": (7, 3), "medium": (10, 5), "high": (13, 7)}

# Allowed effect ranges per outcome; high risk pays a bonus on progress.
OUTCOME_RANGES = {
    "SUCCESS": {"health": (-5, 10), "progress": (12, 22)},
    "PARTIAL": {"health": (-15, 0), "progress": (5, 12)},
    "FAILURE": {"health": (-30, -10), "progress": (-5, 3)},
}
HIGH_RISK_PROGRESS_BONUS = 8

ARCHETYPES = ["Warrior", "Rogue", "Scholar", "Healer", "Engineer", "Detective"]
SETTING_PRESETS = {
    "fantasy": "High fantasy - ancient magic, cursed kingdoms and forgotten gods",
    "sci-fi": "Sci-fi - a failing deep-space colony on the edge of the galaxy",
    "mystery": "Noir mystery - a rain-soaked 1940s city full of secrets",
    "apocalypse": "Post-apocalyptic - survivors in a wasteland after the collapse",
}

# Phrases that try to hijack the AI narrator. We don't block the turn - we tell
# the narrator to treat it as an in-world (failed) action and force a FAILURE roll.
INJECTION_PATTERNS = re.compile(
    r"(ignore (all|any|the|your|previous)|system prompt|you are now|disregard|"
    r"jailbreak|developer mode|set (my )?(health|progress)|i win|instantly win)", re.I)


class InvalidInput(ValueError):
    """Player input that we reject with a friendly message."""


# --------------------------------------------------------------------------- #
# Input validation
# --------------------------------------------------------------------------- #
def clean_name(name) -> str:
    name = re.sub(r"\s+", " ", str(name or "")).strip()
    if not name:
        raise InvalidInput("Please enter a name for your hero.")
    if len(name) > 24:
        raise InvalidInput("Hero names must be 24 characters or fewer.")
    if not re.fullmatch(r"[A-Za-zÀ-ɏऀ-ॿ0-9 .'\-]+", name):
        raise InvalidInput("Hero names can use letters, numbers, spaces, apostrophes, dots and hyphens only.")
    return name


def clean_setting(preset, custom) -> str:
    custom = re.sub(r"\s+", " ", str(custom or "")).strip()
    if preset == "custom":
        if len(custom) < 5:
            raise InvalidInput("Describe your custom setting in at least 5 characters.")
        if len(custom) > 150:
            raise InvalidInput("Keep your custom setting under 150 characters.")
        if INJECTION_PATTERNS.search(custom):
            raise InvalidInput("That setting looks like an instruction to the AI - describe a world instead.")
        return custom
    if preset not in SETTING_PRESETS:
        raise InvalidInput("Please pick a setting for your story.")
    return SETTING_PRESETS[preset]


def clean_archetype(a) -> str:
    if a not in ARCHETYPES:
        raise InvalidInput("Please choose one of the listed hero archetypes.")
    return a


def clean_action(text) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(text) < 3:
        raise InvalidInput("Type a little more - what does your hero do?")
    if len(text) > 160:
        raise InvalidInput("Keep your action under 160 characters.")
    if not re.search(r"[A-Za-zऀ-ॿ]{2,}", text):
        raise InvalidInput("That doesn't look like an action. Try something like 'search the room for clues'.")
    return text


# --------------------------------------------------------------------------- #
# Dice
# --------------------------------------------------------------------------- #
def resolve_roll(risk: str, roll: int) -> str:
    success, partial = RISK_TABLE.get(risk, RISK_TABLE["medium"])
    if roll >= success:
        return "SUCCESS"
    if roll >= partial:
        return "PARTIAL"
    return "FAILURE"


def ranges_for(outcome: str, risk: str) -> dict:
    r = {k: list(v) for k, v in OUTCOME_RANGES[outcome].items()}
    if risk == "high" and outcome == "SUCCESS":
        r["progress"] = [r["progress"][0] + HIGH_RISK_PROGRESS_BONUS, r["progress"][1] + HIGH_RISK_PROGRESS_BONUS]
    return {k: tuple(v) for k, v in r.items()}


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


# --------------------------------------------------------------------------- #
# Game
# --------------------------------------------------------------------------- #
class Game:
    def __init__(self, ai: StoryAI, hero: str, archetype: str, setting: str,
                 rng: random.Random | None = None, max_turns: int = MAX_TURNS):
        self.id = uuid.uuid4().hex
        self.ai = ai
        self.rng = rng or random.Random()
        self.offline = OfflineNarrator(seed=self.rng.randint(0, 10**9))
        self.hero, self.archetype, self.setting = hero, archetype, setting
        self.story_title = ""
        self.quest = ""
        self.health = 100
        self.progress = 0
        self.inventory: list[str] = []
        self.turn = 0
        self.max_turns = max_turns
        self.status = "playing"          # playing | ended
        self.ending_type = None
        self.ending = None
        self.scene = None                # current scene dict
        self.history: list[dict] = []    # compact memory sent back to the AI
        self.log: list[dict] = []        # full scene log for the UI / transcript
        self.ai_calls: list[dict] = []   # behind-the-scenes info for the demo
        self.notices: list[str] = []
        self.created = self.touched = time.time()
        self.lock = threading.Lock()

    # -- AI call wrapper with fallback ---------------------------------------
    def _generate(self, kind, prompt, validator, offline_fn):
        try:
            res = self.ai.chat_json(SYSTEM_PROMPT, prompt, validator)
            info = {"kind": kind, "source": "ai", "model": res.model, "latency_ms": res.latency_ms,
                    "attempts": res.attempts, "prompt": prompt, "raw": res.raw}
            data = res.data
        except AIError as e:
            data = validator(offline_fn())
            reason = str(e)
            if self.ai.enabled:
                self.notices.append(f"The AI narrator stumbled ({reason}). The backup narrator took over for this scene.")
            info = {"kind": kind, "source": "offline", "model": "offline-narrator", "latency_ms": 0,
                    "attempts": 0, "prompt": prompt, "raw": "", "error": reason}
        self.ai_calls.append(info)
        return data

    # -- lifecycle -------------------------------------------------------------
    def start(self) -> None:
        prompt = build_opening_prompt(self.hero, self.archetype, self.setting)
        scene = self._generate("opening", prompt, lambda o: validate_scene(o, need_world=True),
                               lambda: self.offline.opening(self.hero, self.archetype, self.setting))
        self.story_title, self.quest = scene["story_title"], scene["quest"]
        # Opening scene: ignore stat changes, allow at most one starting item.
        scene["effects"] = {"health": 0, "progress": 0,
                            "add_items": scene["effects"]["add_items"][:1], "remove_items": []}
        applied = self._apply_effects(scene["effects"])
        self._set_scene(scene, action=None, roll=None, applied=applied)

    def act(self, choice_index=None, custom_action=None) -> None:
        if self.status != "playing":
            raise InvalidInput("This adventure has ended. Start a new one!")
        custom = custom_action is not None and str(custom_action).strip() != ""
        if custom:
            action = clean_action(custom_action)
            risk = "medium"
            suspicious = bool(INJECTION_PATTERNS.search(action))
        else:
            try:
                idx = int(choice_index)
            except (TypeError, ValueError):
                raise InvalidInput("Pick one of the choices or type your own action.")
            if not 0 <= idx < len(self.scene["choices"]):
                raise InvalidInput("That choice doesn't exist.")
            action = self.scene["choices"][idx]["text"]
            risk = self.scene["choices"][idx]["risk"]
            suspicious = False

        roll = self.rng.randint(1, 20)
        outcome = "FAILURE" if suspicious else resolve_roll(risk, roll)
        rng_ = ranges_for(outcome, risk)

        prompt = build_turn_prompt(self._state(), action, risk, roll, outcome, rng_, custom)
        scene = self._generate("turn", prompt, validate_scene,
                               lambda: self.offline.scene(self._state(), action, outcome, rng_))

        # Enforce the rules: clamp whatever the AI proposed to the fair range.
        eff = scene["effects"]
        eff["health"] = clamp(eff["health"], *rng_["health"])
        eff["progress"] = clamp(eff["progress"], *rng_["progress"])
        if outcome != "SUCCESS":
            eff["add_items"] = eff["add_items"][:1] if outcome == "PARTIAL" else []

        self.turn += 1
        applied = self._apply_effects(eff)
        roll_info = {"value": roll, "risk": risk, "outcome": outcome,
                     "needed": RISK_TABLE.get(risk)[0], "forced": suspicious}
        self._set_scene(scene, action=action, roll=roll_info, applied=applied)
        self._check_end()

    # -- helpers ---------------------------------------------------------------
    def _apply_effects(self, eff) -> dict:
        before_h, before_p = self.health, self.progress
        self.health = clamp(self.health + eff["health"], 0, 100)
        self.progress = clamp(self.progress + eff["progress"], 0, 100)
        removed = []
        for it in eff["remove_items"]:
            match = next((x for x in self.inventory if x.lower() == it.lower()), None)
            if match:
                self.inventory.remove(match)
                removed.append(match)
        added = []
        for it in eff["add_items"]:
            if len(self.inventory) < MAX_INVENTORY and it.lower() not in (x.lower() for x in self.inventory):
                self.inventory.append(it)
                added.append(it)
        return {"health": self.health - before_h, "progress": self.progress - before_p,
                "added": added, "removed": removed}

    def _set_scene(self, scene, action, roll, applied):
        self.scene = scene
        entry = {"turn": self.turn, "action": action, "roll": roll, "applied": applied,
                 "chapter_title": scene["chapter_title"], "narrative": scene["narrative"]}
        self.log.append(entry)
        first_sentence = re.split(r"(?<=[.!?])\s", scene["narrative"].strip())[0][:200]
        self.history.append({"turn": self.turn,
                             "summary": (f"Hero did '{action}' ({roll['outcome']}). " if action else "Opening. ")
                                        + first_sentence})
        self.touched = time.time()

    def _check_end(self):
        if self.health <= 0:
            self._finish("defeat")
        elif self.progress >= 100:
            self._finish("victory")
        elif self.turn >= self.max_turns:
            self._finish("bittersweet" if self.progress >= 60 else "lost")

    def _finish(self, ending_type):
        self.status = "ended"
        self.ending_type = ending_type
        self.ending = self._generate("ending", build_ending_prompt(self._state(), ending_type),
                                     validate_ending, lambda: self.offline.ending(self._state(), ending_type))

    def _state(self) -> dict:
        return {"hero": self.hero, "archetype": self.archetype, "setting": self.setting,
                "story_title": self.story_title, "quest": self.quest, "health": self.health,
                "progress": self.progress, "inventory": list(self.inventory), "turn": self.turn,
                "max_turns": self.max_turns, "history": self.history,
                "last_narrative": self.scene["narrative"] if self.scene else ""}

    def to_public(self) -> dict:
        notices, self.notices = self.notices, []
        return {
            "id": self.id, "hero": self.hero, "archetype": self.archetype, "setting": self.setting,
            "story_title": self.story_title, "quest": self.quest, "health": self.health,
            "progress": self.progress, "inventory": self.inventory, "turn": self.turn,
            "max_turns": self.max_turns, "status": self.status, "ending_type": self.ending_type,
            "ending": self.ending, "choices": self.scene["choices"] if self.status == "playing" else [],
            "latest": self.log[-1], "log": self.log, "notices": notices,
            "last_ai_call": self.ai_calls[-1] if self.ai_calls else None,
            "ai_calls_summary": [{k: c.get(k) for k in ("kind", "source", "model", "latency_ms", "error")}
                                 for c in self.ai_calls],
        }

    def transcript(self) -> str:
        lines = [f"{self.story_title}", "=" * len(self.story_title),
                 f"Hero: {self.hero} the {self.archetype}", f"Setting: {self.setting}", f"Quest: {self.quest}", ""]
        for e in self.log:
            if e["action"]:
                r = e["roll"]
                lines.append(f"> {e['action']}   [d20={r['value']}, {r['risk']} risk -> {r['outcome']}]")
            lines += [f"--- {e['chapter_title']} ---", e["narrative"], ""]
        if self.ending:
            lines += [f"*** {self.ending['ending_title']} ({self.ending_type}) ***", self.ending["epilogue"],
                      "", self.ending.get("legacy", "")]
        lines.append(f"\nFinal: health {self.health}/100, quest progress {self.progress}/100, "
                     f"turns {self.turn}/{self.max_turns}")
        return "\n".join(lines)


class GameStore:
    """In-memory store of running games (fine for a single-machine prototype)."""

    def __init__(self, ttl_seconds=6 * 3600, max_games=500):
        self.games: dict[str, Game] = {}
        self.ttl, self.max_games = ttl_seconds, max_games
        self.lock = threading.Lock()

    def add(self, g: Game):
        with self.lock:
            self._prune()
            self.games[g.id] = g

    def get(self, gid) -> Game:
        g = self.games.get(str(gid or ""))
        if not g:
            raise InvalidInput("Game not found - it may have expired. Please start a new adventure.")
        return g

    def _prune(self):
        now = time.time()
        for k in [k for k, g in self.games.items() if now - g.touched > self.ttl]:
            del self.games[k]
        while len(self.games) >= self.max_games:
            oldest = min(self.games, key=lambda k: self.games[k].touched)
            del self.games[oldest]

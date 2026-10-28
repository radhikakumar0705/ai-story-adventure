# Where and How Generative AI Is Used in *Echoes of Fate*

## Summary
*Echoes of Fate* is an AI story adventure. A large language model (Google Gemini by default; Groq, OpenAI or a local Ollama model also work) acts as the **narrator and game master**. It writes the story **at runtime** in reaction to the player's choices and typed actions. No story text, choices or endings are pre-written. Each playthrough is unique.

## The three AI-generated game elements

| When | What the AI generates | Based on |
|---|---|---|
| **1. Game start** | Story title, the quest goal, the world, the opening scene and the first 3 choices | The player's hero name, archetype and chosen or **custom-typed** world |
| **2. Every turn** | The scene describing the consequence of the player's action, a chapter title, **3 new choices** (low, medium or high risk), items gained or lost, and suggested health and progress changes | The story so far, current stats and inventory, the player's action (chosen **or free-typed**) and the **dice outcome** |
| **3. Game end** | A personalised epilogue and a one-line "legacy" that reference moments from the player's journey | The ending type (victory, defeat, bittersweet or failed) and the full journey |

## How it works technically
1. **Prompting:** a fixed *system prompt* defines the narrator's role, tone (PG-13), the 3-choice format and the rule that it must respect the dice outcome. A *user prompt* is built from the live game state each turn (`ai_engine.py` → `build_opening_prompt`, `build_turn_prompt`, `build_ending_prompt`).
2. **Story memory:** each prompt includes a one-line summary of every past turn plus the full previous scene, so the AI stays consistent.
3. **Structured output:** the model must answer in **JSON** following a fixed schema. The game parses it, validates every field and cleans up common formatting mistakes.
4. **AI proposes, game engine decides:** the AI *suggests* health and progress changes, but the engine **clamps** them to fair ranges for the dice outcome (for example, a failure can't give big progress). This keeps the AI creative and the game fair.
5. **Player-driven:** free-text actions are interpreted by the AI, so the player can try anything. Impossible or rule-breaking actions are narrated as failing in-world.

## Reliability and error handling around the AI
- Malformed AI output is retried with feedback to the model (up to 2 retries).
- Timeouts, network errors and rate limits are retried with back-off.
- If the AI still fails (or there is no API key), a **template-based backup narrator** writes the scene, so the game never crashes, and the player is told.
- Prompt-injection attempts in typed actions ("ignore previous instructions…") automatically fail the dice roll; injection attempts in a custom world description are rejected.
- AI text is always shown as plain text in the browser, never as HTML.

## Seeing it live
The in-game **"Behind the scenes (AI)"** panel lists every AI call (type, model, response time) and shows the **exact prompt** sent and the **raw JSON reply** from the model.

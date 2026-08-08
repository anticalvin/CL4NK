# CL4NK Local Runtime

This is the first runnable CL4NK chassis. It uses only the Python standard library plus a local OpenAI-compatible model server.

## Quick start with Ollama

1. Install Ollama.
2. Pull a model, for example: `ollama pull llama3.2`
3. Start Ollama normally.
4. From the repository root run: `python local/app.py`
5. Open `http://127.0.0.1:4242`

Default runtime URL: `http://127.0.0.1:11434/v1`

Default model: `llama3.2`

Both can be changed in the CL4NK interface.

## What works

- Local chat through an OpenAI-compatible `/v1/chat/completions` endpoint
- Canonical `personality.md` injected as the system identity
- SQLite conversation history
- Explicit durable memories with 1–10 importance
- Delete individual memories
- Clear conversation history
- Runtime URL/model configuration
- Portable JSON identity export/import
- No Python package installation required

## Data ownership

All CL4NK state is stored in `local/cl4nk.db`. Delete that file and the local state is gone. Export an identity bundle before moving machines if you want to preserve conversation and memory.

API keys are stored locally in SQLite if supplied. The export format deliberately does not export API keys.

## Known limitations

This is pre-alpha. Memory retrieval currently injects the highest-priority recent memories rather than using embeddings. Chat is non-streaming. There is no desktop packaging, voice, filesystem tool access, shell execution, automatic memory extraction, encryption-at-rest, or signed release yet.

Those omissions are intentional: the first milestone is a small inspectable companion that actually runs.

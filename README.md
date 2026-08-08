# CL4NK

CL4NK is a local-first, open-source AI companion focused on persistent identity, portable memory, and user-controlled inference.

**HQ:** https://cl-4-nk.vercel.app

## It runs now

The repository now contains the first runnable local chassis in [`local/`](local/README.md).

With Python 3 and Ollama installed:

```bash
ollama pull llama3.2
python local/app.py
```

Then open `http://127.0.0.1:4242`.

The local chassis includes chat through an OpenAI-compatible model server, SQLite conversation history, explicit durable memories, runtime/model configuration, and portable identity export/import. It uses the canonical [`personality.md`](personality.md) as CL4NK's identity core.

## Mission

Build a standalone companion rather than a thin wrapper around a hosted chatbot.

- Local-first companion runtime
- Persistent local memory
- Portable identity export/import
- Replaceable adapters for Ollama, llama.cpp, and other compatible runtimes
- Explicit permission gates for tools
- No mandatory hosted account for the core experience

## Architecture

Vercel hosts CL4NK Headquarters: documentation, roadmap, releases and future downloads. It is not CL4NK's brain.

The first runtime deliberately uses a tiny Python standard-library HTTP service and SQLite so the behavior is inspectable and dependency-light. The next packaging layer can wrap or replace that service with a Tauri desktop shell without changing the identity/memory principles.

## Principles

1. Local-first where practical.
2. The user owns identity and memory data.
3. Hosted services are optional.
4. Model runtimes remain replaceable.
5. Tool permissions are explicit and revocable.
6. Personality never outranks factual accuracy or safety.
7. Prefer mature open-source infrastructure over reinventing solved plumbing.

## Roadmap

- [x] Public project / documentation headquarters
- [x] Canonical personality core
- [x] Runnable local chat chassis
- [x] SQLite conversation + explicit memory store
- [x] Portable identity export/import v1
- [x] OpenAI-compatible local inference adapter
- [x] Turn-aware local memory retrieval v1
- [ ] Memory summaries / forgetting policy
- [ ] Tauri desktop packaging
- [ ] Permissioned tool system
- [ ] Voice
- [ ] Signed/versioned desktop releases

## Status

Pre-alpha, but no longer decorative. There are still no official desktop binaries yet.

## License

MIT

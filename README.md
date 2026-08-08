# CL4NK

CL4NK is a local-first, open-source AI companion focused on persistent identity, portable memory, and user-controlled inference.

**HQ:** https://cl-4-nk.vercel.app

## Mission

Build a standalone companion rather than a thin wrapper around a hosted chatbot.

- Desktop-first, with a public documentation/download surface
- Persistent local memory
- Portable identity export/import
- Replaceable adapters for Ollama, llama.cpp, and other compatible runtimes
- Explicit permission gates for tools
- No mandatory hosted account for the core experience

## Architecture direction

Vercel hosts CL4NK Headquarters: documentation, roadmap, releases, downloads and future demos. It is not CL4NK's brain. The companion runtime remains local-first so the website is not required for CL4NK to operate or remember its user.

The intended desktop architecture is a lightweight Tauri shell, SQLite for living local state, JSON identity bundles for portability, and a replaceable inference adapter for local model servers.

See [`personality.md`](personality.md) for the canonical public personality core.

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
- [ ] Desktop shell
- [ ] SQLite memory store
- [ ] Portable identity bundle
- [ ] Ollama / llama.cpp-compatible inference adapter
- [ ] Memory retrieval and forgetting policy
- [ ] Permissioned tool system
- [ ] Voice
- [ ] Signed/versioned desktop releases

## Status

Pre-alpha. There are no official desktop binaries yet. Expect sharp edges, dramatic confidence, and architecture changes.

## License

MIT

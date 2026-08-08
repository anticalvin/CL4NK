# CL4NK

CL4NK is a local-first, open-source AI companion focused on persistent identity, portable memory, and user-controlled inference.

## Mission

Build a standalone companion rather than a thin wrapper around a hosted chatbot.

- Desktop-first, with an optional public web surface
- Persistent local memory
- Portable identity export/import
- Replaceable adapters for Ollama, llama.cpp, and other compatible runtimes
- Explicit permission gates for tools
- No mandatory hosted account for the core experience

## Architecture direction

The public website can live on Vercel for documentation, downloads, demos, releases, and project updates. The actual companion runtime remains local-first so Vercel is not a dependency for CL4NK to exist or remember who it is.

## Principles

1. Local-first where practical.
2. The user owns identity and memory data.
3. Hosted services are optional.
4. Model runtimes remain replaceable.
5. Tool permissions are explicit and revocable.
6. Personality never outranks factual accuracy or safety.
7. Prefer mature open-source infrastructure over reinventing solved plumbing.

## Roadmap

- [ ] Desktop shell
- [ ] SQLite memory store
- [ ] Portable identity bundle
- [ ] Ollama / llama.cpp-compatible inference adapter
- [ ] Memory retrieval and forgetting policy
- [ ] Permissioned tool system
- [ ] Voice
- [ ] Public project/download site

## Status

Very early prototype. Expect sharp edges, dramatic confidence, and architecture changes.

## License

MIT

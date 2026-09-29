# VirtualCyberQ

High-fidelity emulator of the BBQ Guru CyberQ WiFi: a device plane (:8080)
that serves the real XML/HTTP API, and a separate control plane (:9000) that
drives state, time and faults. Python >=3.10, `src/` layout. `CONTRIBUTING.md`
holds the dev loop and the architectural rules; `docs/CYBERQ_PROTOCOL.md` is
the protocol source of truth.

## Cloud sessions

- The default branch is `master`.
- Dependencies are installed by the SessionStart hook (`.claude/settings.json`
  runs `scripts/cloud-session-start.sh`): `pip install -e ".[dev]"`, into
  `.venv` when the system pip is externally managed. On a developer machine
  the hook does nothing.
- Verify with the CI checks: `ruff check .`, `ruff format --check .`, `mypy`,
  `lint-imports`, `pytest`.
- `tests/fixtures/*.xml` are byte-exact wire captures from a real device
  (CRLF line endings, trailing spaces, no final newline), kept out of git's
  line-ending conversion by `.gitattributes`. Never rewrite, reformat or
  normalise them.
- One task per branch. Push the branch; the owner opens the PR.

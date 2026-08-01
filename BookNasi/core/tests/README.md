# Load-bearing tests

Most tests in this repo protect an implementation. Two protect a **decision**,
and they are marked `@pytest.mark.loadbearing`:

- `test_tenant_isolation.py` — a user must never read another organization's
  data, and must get **404 rather than 403** when they try.
- `test_org_scoped_manager_guard.py` — an org-scoped queryset must refuse to
  execute unless someone named an org.

These two exist because the failure they catch is silent. A cross-tenant read
does not raise, does not log, and does not look wrong in a response body — it
returns rows, and they are somebody else's. By the time anyone notices, it is a
Kenya DPA 2019 incident (CLAUDE.md §9), not a bug report.

**They are not allowed to fail, and they are not allowed to quietly disappear.**
CI runs them by explicit path, so deleting either file fails the build with a
collection error rather than a green run over a smaller suite:

```bash
uv run pytest core/tests/test_tenant_isolation.py core/tests/test_org_scoped_manager_guard.py
```

If a future slice needs to change what these assert, that is a conversation, not
a commit. Every subsequent slice adds models under `OrgScopedModel`, and each
one inherits its safety from here.

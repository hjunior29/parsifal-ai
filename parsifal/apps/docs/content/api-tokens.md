# API tokens

Scripts, the command-line client and AI agents authenticate to the JSON API with a
**personal API token**. A token acts exactly as you: it can see and change the
reviews you are an author or co-author of, nothing else.

## Creating a token

1. Open **Settings → API tokens** (the cog icon in the header, then *API tokens*).
2. Give the token a name that tells you where it is used — for example
   *"Claude Code on my laptop"* — and click **Create token**.
3. Copy the key (`pfl_…`). It is shown **once**: only a hash is stored, so it
   cannot be displayed again. If you lose it, revoke it and create another one.

Administrators can also create tokens from the server:

```bash
python manage.py create_api_token --user alice --name "research assistant"
```

and `python manage.py init --token NAME` prints one for the administrator at
setup time.

## Using a token

```bash
export PARSIFAL_URL=http://localhost:8000
export PARSIFAL_TOKEN=pfl_...
curl -H "Authorization: Bearer $PARSIFAL_TOKEN" $PARSIFAL_URL/api/v1/me
```

The [CLI](/docs/cli/) and the [MCP server](/docs/mcp/) read the same two
environment variables (or a saved profile).

## Revoking

Revoke a token from the same settings page, `parsifal token revoke --id N` or `POST /api/v1/tokens/{id}/revoke`.
A revoked token stays listed until you delete it (**Delete**, `parsifal token delete --id N` or
`DELETE /api/v1/tokens/{id}`); an active token cannot be deleted, revoke it first.
Revoked tokens stop working immediately; the *last used* column helps you spot
tokens that are no longer needed.

## Recommendations

- One token per machine or agent, so revoking one does not break the others.
- Treat tokens like passwords: environment variables or the CLI's config file
  (`~/.config/parsifal/config.toml`, created with mode 600), never in
  repositories or chat transcripts.
- Give an AI agent **its own account and token**: create it under *Review
  settings → Manage access → Create an AI agent as co-author* (or `parsifal
  agent create`). Deleting the agent deletes its account, tokens and everything
  it recorded.
  Decisions the agent records are then attributed to it and can be compared
  with yours — see [Multiple reviewers](/docs/multi-reviewer/).

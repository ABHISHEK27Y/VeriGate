# Organization workspace checkpoint

VeriGate is still an answer-aware semantic caching gateway. This optional
organization configuration maps several gateway credentials to stable subjects,
an organization, trusted applications, allowed technical workspaces, and a
server-owned provider profile. A legacy key keeps its previous private tenant.
No legacy answer is promoted into an organization workspace.

## Free local demonstration

From the repository root on Windows PowerShell, with Python and Docker available:

```powershell
powershell -File scripts/start_org_demo.ps1
```

The script creates an ignored **digest-only** local directory once, validates
the known mock demo's `developer-tool` default `engineering` workspace, then starts
Redis Stack and the gateway with pinned MiniLM, the pinned NLI policy,
prewarming, and a mock provider. It preserves Redis data across restarts. The
first startup downloads model files; the Docker volume persists them. Check
`http://127.0.0.1:8000/ready` and open `http://127.0.0.1:8000/ui`.

For a repeatable semantic hit, explicitly reset only the demo engineering
workspace and seed one labelled factual answer:

```powershell
docker cp scripts/seed_org_demo.py verigate-gateway-1:/tmp/seed_org_demo.py
docker exec -e PYTHONPATH=/app -w /app verigate-gateway-1 python /tmp/seed_org_demo.py
```

Normal startup never clears or reseeds Redis. The fixture is a controlled
answer, not mock generation or production answer-quality evidence. After
seeding, `python -m scripts.verify_org_http evaluation/runs/<new-id>/observations.json`
repeats the HTTP isolation,
routing, deletion, and rotation checks. It clears only the three demo
subjects' private scopes and restores the credential directory afterward.

The development fixture keys are `example-alice-key-12345`,
`example-carol-key-12345`, and `other-dave-key-123456`. They are public demo
credentials, never live secrets. Enter one in the dashboard. For a shared
technical request, ask `Explain how Python decorators work.` as Carol after the explicit fixture
seed. The saved HTTP run returned a HIT with the labelled Python answer. For a
private request, open the development scope override, select **Private**, and ask
the same question with Alice, then Carol: Carol cannot see Alice's private
entry. Dave belongs to a different organization and cannot request
`engineering`. The mock provider's text is a placeholder, not a factual answer.

For exact HTTP requests:

```powershell
$a = @{ 'x-api-key' = 'example-alice-key-12345' }
$c = @{ 'x-api-key' = 'example-carol-key-12345' }
$body = @{prompt='Explain how Python decorators work.'} | ConvertTo-Json
Invoke-RestMethod http://127.0.0.1:8000/v1/chat -Method Post -Headers $a -ContentType application/json -Body $body
Invoke-RestMethod http://127.0.0.1:8000/v1/chat -Method Post -Headers $c -ContentType application/json -Body $body
```

The result reports the authenticated organization/subject, effective scope,
scope-policy version/reason, storage eligibility,
route profile, candidate count, selected rank, model evidence (if invoked),
cache-write outcome, and measured gateway stages. `/admin/cache/occupancy`
accepts `scope=private` or an authorized `scope=workspace&workspace=engineering`
and reports live entry hash memory, estimated-entry count, nearest TTL, stale
memberships, and evictions. It never lists answer text. Browser counters on
`/ui` are per tab, not server totals. The displayed TTL is the configured
value, not the remaining TTL of an individual answer.

An approved application has an administrator-configured default workspace.
Without one, standard requests remain private; the server does not choose the
first workspace implicitly. `cache_scope=private` narrows access and
`cache_scope=none` bypasses lookup and storage. Development scope overrides are
outside the normal dashboard question flow. An actual credential in a request
causes no-store. Personal context may be private-only. A private-only response
is written only to the employee's private namespace. These are conservative
heuristics, not comprehensive data-loss prevention.

## Provisioning and rotation

The directory schema is shown by the generated demo file. Gateway keys are
stored as HMAC-SHA256 digests using `API_KEY_SALT`; provider secrets are named
by `secret_env` and read from the server environment. Keep the salt stable:
changing it invalidates gateway credentials and cache identities. Keep a live
directory and its salt out of Git.

```powershell
$env:VERIGATE_OLD_GATEWAY_KEY = '<old gateway key>'
$env:VERIGATE_NEW_GATEWAY_KEY = '<new gateway key>'
python -m scripts.provision_organization rotate config/organizations-live.json
```

`revoke` uses `VERIGATE_OLD_GATEWAY_KEY`. The running gateway reloads key
status and rotated digests after the file's atomic replacement; a changed
provider profile or workspace definition requires restart. Rotation retains
the subject and authorized cache identity. A user-level clear only clears that
subject's private entries, not the shared workspace. Revoked keys are rejected
before cache lookup or provider access. Rate limits and the optional admitted
request budget follow the stable organization/subject/application identity
through rotation; the budget is not a monetary spending cap.

## Real-provider startup

Create `config/organizations-live.json` with a real `openai` or `gemini`
provider profile, a `secret_env` reference such as `OPENAI_API_KEY`, and only
the intended workspaces and credentials. Set the referenced secret, a private
`API_KEY_SALT` of at least 32 characters, and `METRICS_TOKEN`. Then run:

```powershell
docker compose -f docker-compose.yml -f docker-compose.org-live.yml up -d --build
```

The gateway fails readiness/startup for a missing required model/index and
returns an explicit provider-configuration error if a profile secret is absent.
This command can make paid calls when requests reach a real provider; it has
not been used for this checkpoint. Semantic mode remains experimental. Exact
matching is the deployment default outside these explicit compose overrides.

## Scope and capacity limits

Shared caching requires both a server-authorized workspace/trusted application
and a technical standalone request. Detection can narrow scope but cannot
grant membership. Unknown or sensitive requests fall back to private scope;
responses with detected sensitive material are not cached for organization
keys. The detector is conservative and incomplete. Do not place restricted
documents or user context into this single-turn API.

Shared/private/organization entry and payload-byte limits are configurable. The
byte budgets count stored field values, not Redis keys or vector-index overhead. Redis
transactions update quota metadata across workers; a full or failed write
returns the completed provider answer with a non-success storage outcome.
Oldest entries are evicted on quota pressure. Expiry is finite. The capacity
script `python -m scripts.measure_redis_capacity <new-output.json>` measures
generated fixtures at 100, 500, 1,000, 2,500, and 5,000 entries against Redis
Stack, then clears only its isolated tenant. It does not measure answer quality.
An external answer-body store would be worth reconsidering only if measured
large answers dominate Redis memory enough to justify extra retrieval latency
and consistency complexity.

Duplicate request coalescing remains process local. Two workers can still make
duplicate upstream calls on simultaneous misses. The shared Redis quotas do
not change that behavior.

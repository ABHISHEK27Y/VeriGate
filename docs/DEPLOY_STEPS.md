# VeriGate — Deployment Steps

Everything in the repo is already deploy-ready (Dockerfile, `.gitignore`, HF metadata in
`README.md`, `render.yaml`). What remains needs **your** login, so you do these clicks.

The recommended host is **Hugging Face Spaces** — it's free, needs no credit card, and gives
~16 GB RAM, so the *real* MiniLM semantic embedder runs (Render's free tier is 512 MB and
would crash on the ML model). Render steps are included as a fallback.

---

## Option A — Hugging Face Spaces  ★ recommended

**Why:** free, no card, enough RAM for real embeddings, public URL, resume-worthy.

### One-time
1. Make a free account at https://huggingface.co/join (needs your email — I can't create it).

### Create the Space
2. Go to https://huggingface.co/new-space
3. Fill in:
   - **Owner:** your username
   - **Space name:** `verigate`
   - **License:** mit
   - **SDK:** select **Docker** → **Blank**
   - **Hardware:** CPU basic (free)
   - **Visibility:** Public
4. Click **Create Space**. HF shows you a git URL like
   `https://huggingface.co/spaces/<you>/verigate`.

### Push the code
5. Get a write token: https://huggingface.co/settings/tokens → **New token** → role **Write** → copy it.
6. In a terminal in `D:\miniProject\7th sem\llm-gateway`, run (replace `<you>` and paste the
   token as the password when git asks):
   ```bash
   git remote add space https://huggingface.co/spaces/<you>/verigate
   git push space master:main
   ```
   (Username = your HF username, password = the write token from step 5.)
7. HF now builds the Docker image automatically. Watch the **Logs** tab. First build takes
   ~5-10 min (it downloads CPU PyTorch). When it says **Running**, open the Space URL — the
   dashboard loads and the demo works with `demo-key-123`.

### (Optional) turn on live Gemini answers
By default the Space runs the **mock** provider — zero cost, no key exposed, and it still
demonstrates the full cache/verifier pipeline with real embeddings. To use real Gemini:
8. Space → **Settings** → **Variables and secrets** → add **secrets**:
   - `LLM_PROVIDER` = `gemini`
   - `GEMINI_API_KEY` = *(your key — paste it here, in HF's secret store, never in code)*
   - `GEMINI_MODEL` = `gemini-flash-lite-latest`
   The Space restarts and now returns genuine Gemini answers.

---

## Option B — Render (via GitHub)

1. Push this repo to a GitHub repo (`git remote add origin ... ; git push -u origin master`).
2. https://render.com → sign up (GitHub login).
3. **New +** → **Blueprint** → pick the repo. Render reads `render.yaml` and provisions the
   service with the safe defaults (mock provider, `hash` embeddings so it fits the free tier).
4. Deploy → you get a `https://verigate.onrender.com` URL.
5. For real MiniLM embeddings or live Gemini, upgrade to the `starter` plan and set the env
   vars from the comments in `render.yaml` (add `GEMINI_API_KEY` as a secret in the dashboard).

> Free-tier Render sleeps after 15 min idle; the first request after a nap takes ~30 s to wake.

---

## Option C — Local Docker (no host, runs on your machine)
```bash
docker build -t verigate .
docker run --rm -p 8000:8000 -e LLM_PROVIDER=mock -e EMBEDDING_BACKEND=minilm verigate
# open http://localhost:8000
```

---

## After it's live
- **Public demo URL** → put it on your resume / show in the viva.
- **Updating it:** edit code → `pytest` → `git commit` → `git push space master:main`
  (HF) or `git push` (Render) → it rebuilds and redeploys itself in a few minutes.
- **Security note:** `/metrics` is public in this build (fine for a demo). Before any real
  multi-user use, lock it down per `docs/SECURITY.md` #6.

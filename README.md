# Slide Note

Slide Note is a Vue 3 + FastAPI workspace for uploading PPTX files, reviewing slide content and speaker notes, and using a multimodal chat assistant to draft narration-ready notes.

## Structure

- `frontend`: Vue 3, Element Plus, TypeScript, Vite, Pinia, Vue Router, Tailwind CSS
- `backend`: FastAPI API, PPTX parsing, Ark/OpenAI-compatible model client

## Backend

```bash
conda create -n slide-note python=3.11 -y
conda activate slide-note
pip install -r backend/requirements.txt
cp backend/.env.example backend/.env
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 --app-dir backend
```

Set `ARK_API_KEY` in your shell or `backend/.env`. Do not commit real API keys.

## Frontend

```bash
cd frontend
corepack enable
pnpm install
pnpm dev
```

Build output defaults to `../backend/static`:

```bash
pnpm build
```

You can override it with `VITE_BUILD_OUT_DIR`.


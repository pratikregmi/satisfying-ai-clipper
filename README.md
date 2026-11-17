# Satisfying AI Clipper

Satisfying AI Clipper is a local-first video analysis workspace. It helps creators inspect long-form footage by extracting metadata, finding scenes, transcribing dialogue, and analyzing scene thumbnails with locally run AI. The longer-term goal is to help creators find compelling moments and turn them into short-form videos.

Use the application with footage you own or have permission to use.

## What it does today

- Stores imported video files locally and extracts video metadata.
- Detects scene boundaries and generates scene thumbnails.
- Transcribes speech locally with `faster-whisper`.
- Matches transcript segments to detected scenes.
- Analyzes scene thumbnails with the Ollama vision model and returns structured descriptions, characters, actions, objects, setting, and mood.
- Supports individual and batch scene analysis, plus background analysis jobs with progress tracking.
- Saves scene analyses in SQLite so completed work can be reused.
- Provides a React scene browser for video playback, scene navigation, thumbnails, and transcript review.

The current frontend is a scene browser; clip editing, vertical exports, subtitles, and creative generation are planned, not implemented.

## Technology

- **Backend:** Python 3.13, FastAPI, SQLAlchemy, SQLite
- **Frontend:** React 19, TypeScript, Vite
- **Video and scenes:** FFmpeg/ffprobe, OpenCV, PySceneDetect
- **Speech:** faster-whisper
- **Visual analysis:** Ollama running `qwen3.5:4b` locally

## Requirements

- Python 3.13
- Node.js and npm
- FFmpeg, including `ffprobe`, available on your `PATH`
- Ollama for visual scene analysis

Install the backend Python dependencies:

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -r backend/requirements.txt
```

Install FFmpeg using your operating system's package manager. On macOS with Homebrew:

```bash
brew install ffmpeg
```

Install and start Ollama, then download the model used by the backend:

```bash
ollama pull qwen3.5:4b
```

Ollama should be available at `http://localhost:11434`. Speech transcription uses the Whisper `base` model by default; faster-whisper may download its model files the first time it runs.

## Run locally

From the repository root, start the backend:

```bash
source .venv/bin/activate
python -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8006
```

In another terminal, install frontend dependencies and start Vite:

```bash
cd frontend
npm ci
npm run dev
```

Open [http://127.0.0.1:5173](http://127.0.0.1:5173). The Vite development server proxies `/api` requests to the backend at `http://127.0.0.1:8006`.

The interactive API reference is available at [http://127.0.0.1:8006/docs](http://127.0.0.1:8006/docs), and the backend health endpoint is [http://127.0.0.1:8006/health](http://127.0.0.1:8006/health).

## Typical workflow

1. Upload a video using `POST /api/videos/upload`. The API requires a source name and confirmation that you have permission for commercial reuse.
2. Detect its scenes with `POST /api/videos/{video_id}/detect-scenes`.
3. Generate scene thumbnails with `POST /api/videos/{video_id}/generate-thumbnails`.
4. Start transcription with `POST /api/videos/{video_id}/transcribe`.
5. Match transcript segments to scenes with `POST /api/videos/{video_id}/match-transcript`.
6. Start background AI analysis with `POST /api/videos/{video_id}/analysis/start`, then check progress with `GET /api/videos/{video_id}/analysis/job`.

The frontend currently loads **video ID 2**. If your local database uses a different ID, change `VIDEO_ID` in `frontend/src/App.tsx`.

## Local data and privacy

Processing is designed to run locally. Uploaded videos and generated thumbnails are stored under `media/`; the SQLite database is stored at `backend/data/satisfyingai.db`. Whisper model files are managed by faster-whisper, and Ollama manages its own model files.

These local data directories, model weights, virtual environments, and build outputs are excluded by `.gitignore`. They are not included when you push the project to GitHub. Keep backups of any local videos and database records you want to preserve.

## Development status

The latest progress snapshot provided for video ID 2 was **21 of 617 scenes analyzed**, with 596 remaining and no failures reported. Background analysis processes five scenes per batch by default and stores successful results as they complete, allowing work to resume after interruption.

### Roadmap

1. Complete and improve scene, transcript, and story understanding.
2. Find and rank promising short-form moments, with suggested timestamps and explanations.
3. Create vertical 9:16 clips with subtitles, previews, editing controls, and 1080 × 1920 exports.
4. Add original narration, graphics, animation, transitions, and sound design.
5. Build a creator dashboard for the video library, processing history, recommendations, editing, exports, and rights tracking.

## Frontend checks

Run these commands from `frontend/`:

```bash
npm run lint
npm run build
```
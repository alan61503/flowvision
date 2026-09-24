# Getting Started

This guide covers running FlowVision locally, with Docker, and as a systemd service. For how the pieces fit together, see [Architecture Overview](architecture-overview.md). For the endpoints, see [API Reference](api-reference.md).

### Prerequisites <a href="#prerequisites" id="prerequisites"></a>

| Component | Requirement | Notes |
| --- | --- | --- |
| Python | 3.11 or newer | The Docker image uses 3.12. 3.13 also works. |
| PostgreSQL | Optional | Stores requests, responses and feedback. The API works without it but logs a write error per request. |
| GPU | Optional | PyTorch uses CUDA automatically if available. On CPU a request takes roughly 0.3–1.5 s. |
| RAM | 4 GB or more per worker | Each worker loads all three models (~250 MB on disk). |

The trained models are committed in `src/models/`, so there is nothing extra to download.

### Run locally <a href="#run-locally" id="run-locally"></a>

**1. Create a virtual environment and install dependencies**

```bash
python -m venv .venv
source .venv/bin/activate        # Windows (Git Bash): source .venv/Scripts/activate

# Optional, CPU-only machines: install the much smaller CPU build of PyTorch first
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu

pip install -r requirements.txt
```

**2. Start the server from the repository root**

```bash
python src/run.py
```

Run it from the repository root. Config and model paths (`src/conf/config.yaml`, `src/models/...`) are resolved relative to the current directory, so starting from anywhere else fails with `FileNotFoundError`.

The server listens on port 8000 by default. Startup takes 10–30 seconds while the models load. It is ready when the log shows `Application startup complete`.

**3. Check it works**

```bash
curl http://localhost:8000/
# {"message":"Hi, I am the meter reading assistant."}

curl -X POST http://localhost:8000/flowvision/v1/extract-reading \
  -H "Content-Type: application/json" \
  -d '{"imageURL": "https://example.com/path/to/meter.jpg"}'
```

The image must be reachable over HTTP(S) from the server. To test with a local file, serve its folder with `python -m http.server 8765` and use `http://127.0.0.1:8765/<file>` as the URL.

Interactive API docs are available at `http://localhost:8000/docs` while the server is running.

### Configuration <a href="#configuration" id="configuration"></a>

#### config.yaml <a href="#config-yaml" id="config-yaml"></a>

Settings live in `src/conf/config.yaml`. To use a different file, set the `CONFIG_PATH` environment variable.

| Key | Default | Purpose |
| --- | --- | --- |
| `log_level` | `info` | uvicorn log level (used by `run.py`) |
| `image_download_timeout` | `30` | Seconds to wait when downloading the image |
| `app_server.port` | `8000` | Port used by `run.py` |
| `app_server.app` | `routes:app` | ASGI app used by `run.py` |
| `logs.*` | `logs/...` | Log folders and logger names (see [Logs](#logs)) |
| `models.*` | `src/models/...` | Paths to the three model files |
| `image_enhancement.*` | see file | Sharpening, contrast (CLAHE) and colour boost applied before digit detection |

#### Environment variables <a href="#environment-variables" id="environment-variables"></a>

Environment variables can be set in the shell or in a `.env` file, which is loaded automatically.

| Variable | Default | Purpose |
| --- | --- | --- |
| `CONFIG_PATH` | `src/conf/config.yaml` | Config file location |
| `FLOWVISION_DB_HOST` | `localhost` | PostgreSQL host |
| `FLOWVISION_DB_PORT` | `5432` | PostgreSQL port |
| `FLOWVISION_DB_NAME` | `flowvision` | Database name |
| `FLOWVISION_DB_USERNAME` | `postgres` | Database user |
| `FLOWVISION_DB_PASSWORD` | `postgres` | Database password |

Do not commit real credentials in `.env` files.

### Database setup <a href="#database-setup" id="database-setup"></a>

`flowvision_db_ddl.sql` creates the database, a user and the `flowvision_extraction_data` table. Replace `yourpass` first, then run it as a PostgreSQL superuser:

```bash
psql -U postgres -f flowvision_db_ddl.sql
```

Then point the service at it with the `FLOWVISION_DB_*` variables above. The table layout is described in [Architecture Overview](architecture-overview.md#storage).

### Run with Docker <a href="#run-with-docker" id="run-with-docker"></a>

```bash
docker build -t flowvision .
docker run -p 8000:8000 \
  -e FLOWVISION_DB_HOST=my-db-host \
  -e FLOWVISION_DB_PASSWORD=secret \
  flowvision
```

The container runs gunicorn with uvicorn workers and sizes itself from the available CPUs and GPUs:

* **CPU only:** workers = half the CPUs (between 2 and 8), request timeout 300 s
* **With GPUs:** one worker per GPU (plus one on large machines), request timeout 600 s

It prints its choice at startup, for example `[auto] CPU=8 GPU=0 WORKERS=4 TIMEOUT=300`. To override the automatic sizing, set these with `-e`:

| Variable | Default | Purpose |
| --- | --- | --- |
| `WORKERS` | auto | Number of gunicorn worker processes |
| `TIMEOUT` | auto | Worker timeout in seconds |
| `PREFER_GPU` | `true` | Set to `false` to size workers by CPU even if GPUs are present |
| `GRACEFUL_TIMEOUT` | `60` | Seconds to finish in-flight requests on shutdown |
| `KEEPALIVE` | `30` | HTTP keep-alive seconds |
| `MAX_REQUESTS` / `MAX_REQUESTS_JITTER` | `200` / `50` | Recycle each worker after this many requests |
| `LOG_LEVEL` | `info` | gunicorn log level |

Each worker loads its own copy of the models, so memory use grows with `WORKERS`.

### Run as a systemd service <a href="#run-as-a-systemd-service" id="run-as-a-systemd-service"></a>

`flowvision.service` is an example unit that runs `src/run.py` from a virtual environment. Before installing it, adjust the paths for your server:

* `WorkingDirectory` must be the repository root (the folder containing `src/`), for the reason given in [Run locally](#run-locally).
* `ExecStart` must point at the virtual environment's `python` and at `src/run.py`.

```bash
sudo cp flowvision.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now flowvision
journalctl -u flowvision -f
```

### Logs <a href="#logs" id="logs"></a>

Logs are written under `logs/` in the working directory and rotated at midnight:

| File | Contents |
| --- | --- |
| `logs/api_logs/api.log` | Service events and errors, with stack traces |
| `logs/extraction_request_logs/extraction_request.log` | Every extraction request and response as JSON |
| `logs/feedback_request_logs/feedback_request.log` | Every feedback request and response as JSON |

### Troubleshooting <a href="#troubleshooting" id="troubleshooting"></a>

| Symptom | Cause and fix |
| --- | --- |
| `FileNotFoundError: src/conf/config.yaml` at startup | The server was not started from the repository root. `cd` there, or set `CONFIG_PATH` and absolute model paths. |
| `OperationalError ... connection refused` in `api.log` | PostgreSQL is unreachable. The API keeps working, but nothing is stored. Check the `FLOWVISION_DB_*` variables. |
| Response has `"statusCode": 500` and an error such as `404 Client Error` | The server could not download `imageURL`. Check that the URL is reachable from the server, not just from your machine. |
| Every image comes back `UNCLEAR` / `Image quality too poor for recognition` | The quality model was trained on close-up photos of the meter face. Wide shots that include lots of background are usually rejected. Crop to the meter face. |

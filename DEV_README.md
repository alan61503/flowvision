# Flow Vision

Quick start for developers. Full details are in [Getting Started](getting-started.md).

1. Clone the repository and `cd` into its root directory.
2. Create and activate a virtual environment: `python -m venv .venv`, then `source .venv/bin/activate` (on Windows Git Bash, `source .venv/Scripts/activate`).
3. Install dependencies: `pip install -r requirements.txt`. On a CPU-only machine, you can first run `pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu` to get a much smaller PyTorch.
4. Start the server **from the repository root**: `python src/run.py`. It listens on port 8000 once the models have loaded.
5. Endpoints:
    - `GET /`: liveness check
    - `POST /flowvision/v1/extract-reading`: extract a reading from an image URL
    - `POST /flowvision/v1/feedback`: record whether a reading was correct
6. See the [API Reference](api-reference.md) or the [OpenAPI spec](flowvision_api_spec.yml) for request and response formats. Interactive docs are at `http://localhost:8000/docs`.

To read meters from local photos without starting the server, run `python read_meter.py "water meter.jpg"`. It also accepts several files, a folder, or an image URL.

PostgreSQL is optional for local development. Without it, requests still work, but each one logs a database connection error. See [Getting Started](getting-started.md#database-setup) to set it up.

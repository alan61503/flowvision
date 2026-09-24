# API Reference

FlowVision exposes a small JSON REST API under the base path `/flowvision/v1`. There is no authentication, so put the service behind your own gateway if it is reachable from outside. The machine-readable definition is in [flowvision_api_spec.yml](flowvision_api_spec.yml). A running server also serves interactive docs at `/docs`.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/` | Liveness check |
| `POST` | `/flowvision/v1/extract-reading` | Extract a meter reading from an image URL |
| `POST` | `/flowvision/v1/feedback` | Record whether an extracted reading was correct |

### Liveness check <a href="#liveness-check" id="liveness-check"></a>

`GET /`

```json
{"message": "Hi, I am the meter reading assistant."}
```

This returns as soon as the process is up. The models are loaded before the server starts accepting connections, so a response means the service is ready.

### Extract reading <a href="#extract-reading" id="extract-reading"></a>

`POST /flowvision/v1/extract-reading`

#### Request <a href="#extract-request" id="extract-request"></a>

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `imageURL` | string | Yes | HTTP(S) URL of a JPEG or PNG meter photo, reachable from the server. A presigned S3 URL works. |
| `id` | UUID | No | Your request ID. Generated if omitted. It is echoed back and used as the database key. |
| `ts` | datetime | No | Request timestamp (ISO 8601 or Unix seconds). Defaults to the time of receipt. |
| `metadata` | object | No | Any JSON object, such as a meter or site ID. Stored with the request. |

```json
{
  "id": "2800d121-02b4-471d-bc33-be3a56f8db2a",
  "imageURL": "https://my-bucket.s3.amazonaws.com/meters/1234.jpg",
  "metadata": {"meterId": "M7711086"}
}
```

For best results, the photo should be a close-up of the meter face with the digit window clearly visible. Wide shots that include lots of surroundings are often rejected by the quality check.

#### Response <a href="#extract-response" id="extract-response"></a>

| Field | Type | Description |
| --- | --- | --- |
| `id` | UUID | The request ID |
| `ts` | datetime | Response time |
| `responseCode` | `OK` / `ERROR` | Whether the request was processed |
| `statusCode` | integer | `200` when processed, `500` on error |
| `result.status` | `SUCCESS` / `UNCLEAR` | Outcome (see [Status values](#status-values)) |
| `result.correlationId` | UUID | Pass this to `/feedback` to rate the reading |
| `result.data.meterReading` | string | The digits read left to right, leading zeros kept, no decimal point. On `UNCLEAR`, a short reason instead. |
| `result.data.qualityStatus` | `good` / `bad` | Result of the image quality check |
| `result.data.qualityConfidence` | number 0–1 | Confidence of the quality check |
| `result.data.lastDigitColor` | `black` / `red` / `unknown` | Colour of the rightmost digit wheel. A red wheel usually means a fractional digit. `unknown` when no digits were read. |
| `result.data.colorConfidence` | number 0–1 | Confidence of the colour result (`0` when `unknown`) |
| `result.data.processingTime` | number | Seconds spent on the request, including the image download |

Fields that are `null` are left out of the response.

**Success**

```json
{
  "id": "44939270-210b-467d-a73a-ca32d9ee8591",
  "ts": "2026-09-24T10:40:17.559018",
  "responseCode": "OK",
  "statusCode": 200,
  "result": {
    "status": "SUCCESS",
    "correlationId": "71e6df84-463a-4fd7-b659-769e20bbbf23",
    "data": {
      "meterReading": "024965",
      "processingTime": 0.466612,
      "qualityStatus": "good",
      "qualityConfidence": 0.6665819883346558,
      "lastDigitColor": "black",
      "colorConfidence": 0.9722830057144165
    }
  }
}
```

**Image rejected by the quality check**

```json
{
  "id": "5054dd8b-d4cb-43b4-952b-97ccfa2d60ce",
  "ts": "2026-09-24T10:48:24.504769",
  "responseCode": "OK",
  "statusCode": 200,
  "result": {
    "status": "UNCLEAR",
    "correlationId": "43421856-db05-4a46-a2a3-00d59112d37f",
    "data": {
      "meterReading": "Image quality too poor for recognition",
      "processingTime": 0.173178,
      "qualityStatus": "bad",
      "qualityConfidence": 0.8968913555145264,
      "lastDigitColor": "unknown",
      "colorConfidence": 0.0
    }
  }
}
```

**Error** (for example, when the image URL returns 404)

```json
{
  "id": "b901b35c-7b24-4ad0-a1e9-1d1f853e127c",
  "ts": "2026-09-24T10:48:25.413109",
  "responseCode": "ERROR",
  "statusCode": 500,
  "error": {
    "errorCode": 500,
    "errorMsg": "404 Client Error: Not Found for url: https://my-bucket.s3.amazonaws.com/meters/missing.jpg"
  }
}
```

> **Important:** error responses are sent with **HTTP status 200**. Check `responseCode` (or `statusCode`) in the body to detect failures. Only an invalid request body produces a non-200 HTTP status (422, see [Validation errors](#validation-errors)).

#### Status values <a href="#status-values" id="status-values"></a>

| `result.status` | When | `meterReading` |
| --- | --- | --- |
| `SUCCESS` | The image passed the quality check and at least one digit was read | The digits, for example `"024965"` |
| `UNCLEAR` | The quality check returned `bad` | `"Image quality too poor for recognition"` |
| `UNCLEAR` | The quality check passed but no digits were detected | `"No digits detected in the image"` |
| `NOMETER` | Reserved in the schema. Not currently returned. | |

A `SUCCESS` status means digits were read, not that they are correct. Use `qualityConfidence`, and ideally a sanity check against the previous reading, before trusting a value automatically.

### Feedback <a href="#feedback" id="feedback"></a>

`POST /flowvision/v1/feedback`

Records whether an extracted reading was correct, for accuracy tracking and model retraining.

#### Request <a href="#feedback-request" id="feedback-request"></a>

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `correlationId` | UUID | Yes | `result.correlationId` from the extraction response |
| `data.accurate` | boolean | Yes | Whether the extracted reading was correct |
| `data.actual` | number | No | The correct reading, if known |
| `data.extracted` | number | No | The reading that was extracted (logged, not stored) |
| `id` | UUID | No | Your request ID. Generated if omitted. |
| `ts` | datetime | No | Feedback timestamp. Defaults to the time of receipt. |

```json
{
  "correlationId": "71e6df84-463a-4fd7-b659-769e20bbbf23",
  "data": {"accurate": false, "extracted": 24965, "actual": 24963}
}
```

#### Response <a href="#feedback-response" id="feedback-response"></a>

```json
{
  "id": "772d8818-9cf0-41f4-87e7-c24867d84e4d",
  "ts": "2026-09-24T10:48:25.540585",
  "responseCode": "OK",
  "statusCode": 200,
  "result": {"status": "SUBMITTED"}
}
```

`SUBMITTED` means the feedback was accepted. It is saved to the database in the background after the response is sent. If that save fails, the failure is only logged, so the client still sees `SUBMITTED`.

### Validation errors <a href="#validation-errors" id="validation-errors"></a>

A request body that doesn't match the schema, such as a missing `imageURL` or an `id` that isn't a UUID, is rejected with HTTP **422** and FastAPI's standard error body:

```json
{
  "detail": [
    {"type": "missing", "loc": ["body", "imageURL"], "msg": "Field required", "input": {}}
  ]
}
```

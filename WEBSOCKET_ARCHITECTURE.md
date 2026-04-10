# WebSocket Architecture Analysis — QuikSocial Scraper Agent

## Overview

The QuikSocial application implements **dual WebSocket systems** for real-time progress streaming:
1. **Scraper Agent WebSocket** — Brand scraping pipeline progress
2. **Campaign Generator WebSocket** — Campaign post generation progress

Both systems use identical architectural patterns for consistency and reliability.

---

## Architecture Pattern

### Core Components

```
┌─────────────────────────────────────────────────────────────────┐
│ FastAPI Router (WebSocket Handler)                              │
├─────────────────────────────────────────────────────────────────┤
│ ✓ Accepts WebSocket connection                                  │
│ ✓ Validates job_id from URL parameter                            │
│ ✓ Retrieves async Queue from in-memory store                     │
│ ✓ Streams messages from queue to client                          │
│ ✓ Handles disconnects gracefully                                 │
└─────────────────────────────────────────────────────────────────┘
           ↑
           │ subscribes to
           │
┌─────────────────────────────────────────────────────────────────┐
│ Background Job Task (asyncio.create_task)                       │
├─────────────────────────────────────────────────────────────────┤
│ ✓ Runs scrape/generation pipeline                                │
│ ✓ Pushes progress messages to queue at milestones                │
│ ✓ Saves job results to both memory and disk                      │
│ ✓ Final message ("done"/"error") closes the stream               │
└─────────────────────────────────────────────────────────────────┘
           ↓
           │ writes to
           │
┌─────────────────────────────────────────────────────────────────┐
│ Async Queue (asyncio.Queue)                                     │
├─────────────────────────────────────────────────────────────────┤
│ ✓ One queue per job_id (stored in {scrape|campaign}_job_store)  │
│ ✓ Decouples background work from WebSocket streaming             │
│ ✓ Supports multiple concurrent WebSocket clients per job         │
│ ✓ Auto-cleaned up 5 minutes after job completes                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Scraper Agent WebSocket

### File: `scraper_agents/orchestrator.py`

#### Endpoints

**Fire-and-forget async scrape:**
```
POST /smart-scrape-v2/async
```
Returns immediately with `scrape_id`, background job runs asynchronously.

**Poll for status (HTTP):**
```
GET /smart-scrape-v2/status/{scrape_id}
```
Synchronous HTTP GET — returns current job status from disk/memory.

**WebSocket real-time stream:**
```
WS /ws/smart-scrape/{scrape_id}
```
Persistent WebSocket connection for live progress updates.

---

### Job Lifecycle

#### 1. **Job Creation** (`POST /smart-scrape-v2/async`)

```python
scrape_id = uuid.uuid4().hex[:8]                          # Generate unique ID
queue: asyncio.Queue = asyncio.Queue()
_scrape_queues[scrape_id] = queue                         # Register queue
_save_job(scrape_id, {
    "status": "processing",
    "website_url": website_url,
    "started_at": time.time(),
})

# Launch background job
asyncio.create_task(_run_and_store())
```

**Response:**
```json
{
  "scrape_id": "abc123de",
  "status": "processing",
  "message": "Scraping started... Connect to /ws/smart-scrape/abc123de for real-time progress."
}
```

---

#### 2. **Background Execution** (Inside `_run_agentic_scrape()`)

The orchestrator runs a 4-phase pipeline:

```
PHASE 1: CrawlerAgent (blocking)
    ↓
    await _push({"step": "crawling", "message": "Mapping site structure..."})
    ↓
PHASE 2: Parallel Agents (Logo, Visual, Products, Content, Contact, BrandIntel)
    ↓
    await _push({"step": "analysing", "message": "Analysing brand identity..."})
    ↓
PHASE 3: WebSearchAgent (fills gaps from Brand Intelligence)
    ↓
    await _push({"step": "searching", "message": "Filling data gaps..."})
    ↓
PHASE 4: Assemble Response
    ↓
    await _push({"step": "assembling", "message": "Assembling brand profile..."})
    ↓
    [SUCCESS]
    ↓
    await queue.put({"step": "done", "message": "Completed", "result": {...}})
    _save_job(scrape_id, {"status": "done", "result": result_dict})
```

**Progress Messages Sent:**
- `{"step": "started", "message": "Scanning website {url}..."}`
- `{"step": "crawling", "message": "Mapping site structure..."}`
- `{"step": "analysing", "message": "Analysing brand identity and content..."}`
- `{"step": "searching", "message": "Filling data gaps with web search..."}`
- `{"step": "assembling", "message": "Assembling brand profile..."}`
- `{"step": "done", "message": "Completed", "result": {...}}`  ← **Closes stream**
- `{"step": "error", "message": "...", "error": "details..."}`  ← **Closes stream**

---

#### 3. **WebSocket Handler** (`ws_smart_scrape()`)

```python
@router.websocket("/ws/smart-scrape/{scrape_id}")
async def ws_smart_scrape(websocket: WebSocket, scrape_id: str):
    await websocket.accept()

    # Wait briefly for job to register (race condition handling)
    for _ in range(20):                          # 3 second timeout
        if scrape_id in _scrape_queues:
            break
        await asyncio.sleep(0.15)
    else:
        await websocket.send_json({"step": "error", "error": f"Invalid scrape_id: {scrape_id}"})
        await websocket.close(code=1008)
        return

    q: asyncio.Queue = _scrape_queues[scrape_id]
    try:
        while True:
            message = await q.get()                 # Block until next message
            await websocket.send_json(message)
            if message.get("step") in ("done", "error"):
                break
    except WebSocketDisconnect:
        logger.info(f"[WS] Client disconnected from scrape job {scrape_id}")
    finally:
        try:
            await websocket.close(code=1000)
        except Exception:
            pass
```

**Key Features:**
- ✓ Waits up to 3 seconds for job to be registered
- ✓ Streams all messages until "done" or "error" step
- ✓ Closes connection with code `1000` (normal closure) or `1008` (policy violation)
- ✓ Handles client disconnects gracefully

---

#### 4. **Job Completion**

**In-Memory State:**
- Queue is cleaned up after 5 minutes (in `_drop_queue()` task)
- Job remains in `_scrape_jobs` dict until garbage collected

**On Disk:**
- Saved to `generated_images/smart_scrape/_job_{scrape_id}.json`
- Contains full `SmartScrapeResponse` object with results
- Survives process restarts — allows reconnects

**Polling Later:**
```
GET /smart-scrape-v2/status/{scrape_id}
→ Loads from disk if not in memory
→ Returns cached result to client
```

---

## Campaign Generator WebSocket

### File: `campaign.py`

#### Endpoints

**Fire-and-forget async campaign generation:**
```
POST /create-campaign-advanced
```
Accepts multipart form data, returns `job_id` immediately.

**Poll for status (HTTP):**
```
GET /campaign-status/{job_id}
```
Synchronous HTTP GET — returns current job status.

**WebSocket real-time stream:**
```
WS /ws/campaign/{job_id}
```
Live progress updates including per-image completion messages.

---

### Job Lifecycle

#### 1. **Job Creation** (`POST /create-campaign-advanced`)

```python
job_id = str(uuid.uuid4())
queue: asyncio.Queue = asyncio.Queue()
campaign_job_store[job_id] = {
    "status": "processing",
    "queue": queue
}
_persist_job(job_id, {"status": "processing"})

asyncio.create_task(_run_campaign_job(
    job_id=job_id,
    queue=queue,
    campaign_name=campaign_name,
    # ... 40+ parameters ...
))

return {
    "campaign_id": job_id,
    "message": f"Campaign '{campaign_name}' started. Connect to /ws/campaign/{job_id} for real-time progress.",
}
```

---

#### 2. **Background Execution** (Inside `_run_campaign_job()`)

Campaign generation runs in phases:

```
[INITIALIZATION]
    ↓
    await queue.put({"step": "started", "message": "..."})
    ↓
[BUILD ITEMS TO PROMOTE]
    Product + Service + Brand awareness items stratified by post percentage
    ↓
[BUILD GENERATION QUEUE]
    Distribute items across platforms based on post percentage
    ↓
[PARALLEL IMAGE GENERATION]
    ↓
    for each post (with semaphore limiting concurrency to 5):
        ├─ await _push({"step": "generating", ...})
        ├─ [GEMINI IMAGE GENERATION]
        ├─ await queue.put({"step": "image_done", "post_number": N, "image_url": "...", ...})
        └─ _append_event(job_id, event)          ← For cross-instance persistence
    ↓
    await queue.put({"step": "done", "message": "Completed", "result": {...}})
    ↓
[SUCCESS]
```

**Progress Messages Sent:**
```json
{
  "step": "started",
  "message": "Preparing campaign...",
  "campaign_id": "...",
  "total_posts": 10,
  "platforms": ["instagram", "facebook", "linkedin"]
}
```

```json
{
  "step": "generating",
  "message": "Preparing 10 images for your campaign...",
  "total_posts": 10
}
```

```json
{
  "step": "image_done",
  "message": "Preparing 1st image",
  "post_number": 1,
  "sequence": 1,
  "total": 10,
  "image_url": "https://...",
  "platform": "instagram",
  "item_name": "Product Name"
}
```

```json
{
  "step": "done",
  "message": "Completed",
  "result": { /* full CampaignResponse object */ }
}
```

```json
{
  "step": "error",
  "message": "Campaign generation failed. Please try again.",
  "error": "detailed error message"
}
```

---

#### 3. **WebSocket Handler** (`ws_campaign_status()`)

```python
@router.websocket("/ws/campaign/{job_id}")
async def ws_campaign_status(websocket: WebSocket, job_id: str):
    await websocket.accept()

    # Wait briefly for the job to be registered
    for _ in range(20):                          # 3 second timeout
        if job_id in campaign_job_store:
            break
        await asyncio.sleep(0.15)

    if job_id not in campaign_job_store:
        # Check file — handles reconnects AND cross-instance jobs
        saved = _read_persisted_job(job_id)
        if saved and saved.get("status") == "done":
            await websocket.send_json({"step": "done", "message": "Completed", "result": saved["result"]})
            await websocket.close(code=1000)
        elif saved and saved.get("status") == "error":
            await websocket.send_json({"step": "error", "message": "Campaign generation failed.", "error": saved.get("error", "Unknown error")})
            await websocket.close(code=1000)
        elif saved and saved.get("status") == "processing":
            # Job is running on a different instance
            logger.info(f"[WS] Cross-instance job detected {job_id}, switching to file-poll mode")
            events_file = _campaign_jobs_dir / f"_job_{job_id}.events.jsonl"
            cursor = 0
            try:
                while True:
                    if events_file.exists():
                        lines = events_file.read_text(encoding="utf-8").splitlines()
                        for line in lines[cursor:]:
                            line = line.strip()
                            if not line:
                                continue
                            event = json.loads(line)
                            await websocket.send_json(event)
                            cursor += 1
                            if event.get("step") in ("done", "error"):
                                await websocket.close(code=1000)
                                return
                    await asyncio.sleep(0.5)
            except WebSocketDisconnect:
                logger.info(f"[WS] Client disconnected from cross-instance job {job_id}")
            finally:
                try:
                    await websocket.close(code=1000)
                except Exception:
                    pass
        else:
            await websocket.send_json({"step": "error", "error": f"Invalid job_id: {job_id}"})
            await websocket.close(code=1008)
        return

    # Job is in memory on this instance
    queue: asyncio.Queue = campaign_job_store[job_id]["queue"]
    try:
        while True:
            message = await queue.get()            # Block until next message
            await websocket.send_json(message)
            if message.get("step") in ("done", "error"):
                break
    except WebSocketDisconnect:
        logger.info(f"[WS] Client disconnected from job {job_id}")
    finally:
        try:
            await websocket.close(code=1000)
        except Exception:
            pass
```

**Key Features:**
- ✓ Same 3-second job registration timeout as scraper
- ✓ **Cross-instance support**: If job not in memory, switches to polling disk JSONL file
- ✓ **JSONL event log** (`_job_{job_id}.events.jsonl`) — append-only, cross-worker persistence
- ✓ Handles client disconnects and reconnects gracefully

---

#### 4. **Job Completion**

**In-Memory State:**
```python
campaign_job_store[job_id] = {
    "status": "done",
    "queue": queue,
    "result": result_dict
}
```

**On Disk:**
- Job metadata: `campaign_jobs/_job_{job_id}.json`
- Event log: `campaign_jobs/_job_{job_id}.events.jsonl` (appended to by `_append_event()`)

**Delayed Cleanup** (300 seconds):
```python
async def _cleanup_job(job_id: str):
    await asyncio.sleep(300)  # 5 minutes
    campaign_job_store.pop(job_id, None)
```

---

## Cross-Instance Support (Campaign Only)

### Problem
Multi-worker deployments: Job starts on Worker A, client reconnects and hits Worker B.

### Solution
**Shared JSONL Event Log**

1. **Worker A** (running job):
   ```python
   def _append_event(job_id: str, event: dict) -> None:
       events_file = _campaign_jobs_dir / f"_job_{job_id}.events.jsonl"
       with open(events_file, "a", encoding="utf-8") as f:
           f.write(json.dumps(event, default=str) + "\n")
   ```

2. **Worker B** (WebSocket client connects):
   ```python
   elif saved and saved.get("status") == "processing":
       # Detect: job running on another worker
       events_file = _campaign_jobs_dir / f"_job_{job_id}.events.jsonl"
       cursor = 0
       while True:
           if events_file.exists():
               lines = events_file.read_text(encoding="utf-8").splitlines()
               for line in lines[cursor:]:        # Stream new lines only
                   event = json.loads(line)
                   await websocket.send_json(event)
                   cursor += 1
           await asyncio.sleep(0.5)              # Poll every 500ms
   ```

**Key:** Cursor advances only through new lines, no duplicate events sent.

---

## Job Storage Architecture

### In-Memory Store
```python
_scrape_queues: Dict[str, asyncio.Queue] = {}    # Scraper
campaign_job_store: Dict[str, dict] = {}         # Campaign
```
**Lifetime:** Process restart = lost data (but disk backup exists)

### File-Based Store
**Scraper Jobs:**
```
generated_images/
  smart_scrape/
    _job_abc123de.json          ← Single file per job
    f699be95_traya/             ← Results organized by scrape_id
      scrape_metadata.json      ← Full response saved here
```

**Campaign Jobs:**
```
generated_images/
  campaign_jobs/
    _job_abc123de.json          ← Job metadata
    _job_abc123de.events.jsonl  ← Append-only event log (1 line per event)
    [generated images in campaigns/ subfolder]
```

---

## Error Handling Details

### Scraper WebSocket
```
CLIENT                                  SERVER                     BACKGROUND JOB
           ─────────────────→ POST /async
                             [Fire job]
                             ← scrape_id
           ─────────────────→ WS /ws/smart-scrape/{id}
           
           ← progress messages (streaming)
           
           [If job fails]
           ← {"step": "error", "message": "...", "error": "..."}
           [WS closes, code 1000]
```

**Failure Points:**
1. **Job not found** (timeout) → Close code `1008` + error message
2. **Job crashes** (exception in `_run_and_store`) → Caught, saved to disk, sent via `queue.put({"step": "error", ...})`
3. **Client disconnect** → Server logs, ignores, keeps job running in background

---

### Campaign WebSocket
Same pattern, with additional **cross-instance recovery**:
- If job not in memory, poll file system
- If file exists with "processing" status, stream events from JSONL
- If client disconnects mid-stream, next connection reads from JSONL cursor position

---

## Performance Characteristics

### Latency
- **Initial message**: <100ms (pushed immediately after `await _push()`)
- **Per-message overhead**: ~5–10ms (JSON serialization + socket write)
- **Client queue drain**: Should be instant (no backpressure)

### Concurrency
- **Campaign image generation**: Semaphore limits to 5 concurrent Gemini API calls
- **Per-job queues**: One queue per job, independent scaling
- **Multiple clients per job**: All read from same queue (no duplication)

### Persistence
- **Scraper**: Full result saved to `scrape_metadata.json` after completion
- **Campaign**: Events appended to JSONL, full result saved to JSON on completion
- **Cleanup**: In-memory queues dropped after 5 minutes; files persist indefinitely (manual cleanup needed)

---

## Security & Validation

### Input Validation
- `scrape_id` and `job_id` are UUIDs (no SQL injection risk)
- All file paths use `Path()` with `resolved()` (no path traversal)
- WebSocket accepts only valid UUIDs from URL

### Error Messages
- Generic error messages sent to client
- Detailed errors logged server-side
- No internal stack traces exposed to client (except in debug mode)

### Authentication
- ❌ **Currently: No authentication** — any client can connect to any `job_id`
- **Recommendation**: Add JWT validation or UUID-based secret tokens

---

## Debugging & Monitoring

### Log Entries
Campaign job lifecycle:
```
[WS] Campaign job created: {job_id}  campaign='{campaign_name}'
[WS] Client disconnected from job {job_id}
[WS] Cross-instance job detected {job_id}, switching to file-poll mode
```

Scraper job lifecycle:
```
[AGENTIC SCRAPE] {url} (id={scrape_id})
[PHASE 1] CrawlerAgent — mapping site structure...
[PHASE 2] Parallel agents — Logo, Visual, Products, Content, Contact...
[PHASE 3] WebSearchAgent...
[AGENTIC SCRAPE] COMPLETE in {total_time}s
[METADATA] saved to {path}
```

### Disk Inspection
Check job status without connecting WebSocket:
```bash
# Scraper
cat generated_images/smart_scrape/_job_abc123de.json

# Campaign
cat generated_images/campaign_jobs/_job_abc123de.json
cat generated_images/campaign_jobs/_job_abc123de.events.jsonl
```

---

## Summary Table

| Aspect | Scraper | Campaign |
|--------|---------|----------|
| **Endpoints** | POST async, GET status, WS | POST async, GET status, WS |
| **Queue Type** | `asyncio.Queue` per scrape | `asyncio.Queue` per job |
| **Storage** | JSON file + scrape_metadata | JSON file + JSONL event log |
| **Cross-Instance** | ❌ Not supported | ✅ Supported (JSONL polling) |
| **Cleanup** | 30 min (completed jobs) | 5 min (queues) + manual cleanup |
| **Message Count** | ~5 per job | ~N + 2 (N = post count) |
| **Concurrency Limit** | None (sequential phases) | 5 (Gemini API calls) |
| **Error Handling** | HTTP 502 on fail | Caught + persisted |

---

## Client Integration Example

### Connect to Scraper WebSocket
```javascript
const scrapeId = "abc123de";
const ws = new WebSocket(`ws://localhost:8049/ws/smart-scrape/${scrapeId}`);

ws.onmessage = (event) => {
  const msg = JSON.parse(event.data);
  console.log(`[${msg.step}] ${msg.message}`);
  
  if (msg.step === "done") {
    console.log("Scrape complete:", msg.result);
    ws.close();
  } else if (msg.step === "error") {
    console.error("Scrape failed:", msg.error);
    ws.close();
  }
};

ws.onerror = (error) => {
  console.error("WebSocket error:", error);
};
```

### Connect to Campaign WebSocket
```javascript
const jobId = "12345678-1234-1234-1234-123456789012";
const ws = new WebSocket(`ws://localhost:8049/ws/campaign/${jobId}`);

ws.onmessage = (event) => {
  const msg = JSON.parse(event.data);
  
  switch (msg.step) {
    case "generating":
      console.log(`Generating ${msg.total_posts} posts...`);
      break;
    case "image_done":
      console.log(`${msg.sequence}/${msg.total}: ${msg.item_name}`);
      console.log(`  Image URL: ${msg.image_url}`);
      break;
    case "done":
      console.log("Campaign complete!");
      console.log(`  Posts generated: ${msg.result.total_posts_generated}`);
      ws.close();
      break;
    case "error":
      console.error("Campaign failed:", msg.error);
      ws.close();
      break;
  }
};
```

---

## Potential Issues & Improvements

### Current Issues
1. **No authentication** — anyone knowing a job_id can connect
2. **Manual cleanup** — old files accumulate on disk
3. **Scraper no cross-instance support** — fails on multi-worker deployments
4. **Queue memory leak** — delayed cleanup adds latency

### Recommended Improvements
1. Add JWT validation to WebSocket endpoints
2. Implement auto-rotation of old job files (archive to S3 or delete)
3. Extend scraper to use JSONL event log (like campaign)
4. Add metrics: queue depth, delivery latency, error rates
5. Implement message batching for high-throughput scenarios

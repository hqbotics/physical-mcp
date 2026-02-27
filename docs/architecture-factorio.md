# physical-mcp — Factory Blueprint

```
╔═══════════════════════════════════════════════════════════════════════════════════════════════╗
║                                                                                               ║
║   PHYSICAL-MCP v1.2.0                                    ██▓▓ FACTORY BLUEPRINT ▓▓██          ║
║   "Give your AI eyes"                                                                         ║
║                                                          52 modules · 506 tests · MIT         ║
║   Throughput: cameras ──► frames ──► insights ──► alerts                                      ║
║                                                                                               ║
╚═══════════════════════════════════════════════════════════════════════════════════════════════╝


═══ MINING OUTPOST ═══                 ═══ ORE PROCESSING ═══              ═══ SMELTING ═══

  Extracts raw frames from              Buffers & detects change            Decides WHEN to
  physical world cameras                 locally (<5ms, free)               call the LLM ($$$)

 ┌───────────────────┐                ┌──────────────────┐               ┌──────────────────┐
 │  ⛏  USB Camera    │    frames     │                  │   ChangeResult│                  │
 │     usb.py        │───(jpg)──────►│   FrameBuffer    │──(level,diff)►│   FrameSampler   │
 │                   │  ·            │   buffer.py      │               │   frame_sampler  │
 │  OpenCV capture   │  ·  ┌────────│                  │  ┌────────────│                  │
 │  bg thread @ 2fps │  ·  │        │  async ring:300  │  │            │  debounce 3s     │
 │  device_index: N  │  ·  │        │  lock + event    │  │            │  cooldown 10s    │
 └───────────────────┘  ·  │        └──────────────────┘  │            │  heartbeat: 0    │
                        ·  │             ▲                 │            └────────┬─────────┘
 ┌───────────────────┐  ·  │             │                 │                     │
 │  ⛏  RTSP Camera   │  ·  │        ┌────┴─────────────┐  │              should_analyze?
 │     rtsp.py       │──·──┘        │                  │  │                     │
 │                   │              │  ChangeDetector   │──┘               yes ──┤── no ──► (idle)
 │  ffmpeg decode    │              │  change_detector  │                        │
 │  auto-reconnect   │              │                  │                        ▼
 │  exp. backoff     │              │  pHash + pixel    │
 │  2s → 30s retry   │              │  diff, <5ms       │
 └───────────────────┘              │  thresholds:      │
                                    │   minor: 5        │
 ┌───────────────────┐              │   moderate: 12    │
 │  ⛏  Camera        │              │   major: 25       │
 │     Factory       │              └──────────────────┘
 │     factory.py    │
 │                   │
 │  config → USB     │
 │  config → RTSP    │
 │  validates type   │
 └───────────────────┘


═══ CHEMICAL PLANT (LLM Vision) ═══════════════════════════════════════════════════════════════

  Frame + scene context → external LLM API → structured JSON analysis
  This is the ONLY part that costs money. Zero calls when no rules or static scene.

                          ┌──────────────────────────────────────────────────┐
                   frame  │                                                  │  analysis JSON
         ─────(base64)───►│             FrameAnalyzer                        │──────────────►
                          │             reasoning/analyzer.py                │
                          │                                                  │   { summary,
                          │  Encodes frame → builds prompt → calls provider  │     objects,
                          │  Parses JSON response → validates → returns      │     people,
                          │  Retry: 0 (fail fast, don't burn tokens)         │     changes }
                          │                                                  │
                          └──────────────┬───────────────────────────────────┘
                                         │ selects provider
                          ┌──────────────┴───────────────────────────────────┐
                          │         reasoning/factory.py                      │
                          │                                                   │
                          │  ┌─────────────┐ ┌─────────────┐ ┌────────────┐  │
                          │  │  Anthropic   │ │   Google    │ │  OpenAI    │  │
                          │  │ (Claude)     │ │  (Gemini)   │ │  Compat    │  │
                          │  │ anthropic.py │ │  google.py  │ │  openai_   │  │
                          │  │             │ │             │ │  compat.py │  │
                          │  │  Anthropic   │ │  genai SDK  │ │  OpenRouter│  │
                          │  │  Messages    │ │  Flash/Pro  │ │  Kimi K2.5 │  │
                          │  │  API         │ │             │ │  any OAPI  │  │
                          │  └─────────────┘ └─────────────┘ └────────────┘  │
                          │                                                   │
                          │  json_extract.py — multi-strategy JSON repair     │
                          │  (markdown fences, truncation, noise)             │
                          │                                                   │
                          │  prompts.py — system + analysis prompt templates  │
                          └───────────────────────────────────────────────────┘


═══ ASSEMBLER (Rule Evaluation) ════════════════════════════════════════════════════════════════

  Takes LLM analysis + current rules → evaluates each condition → fires alerts

   analysis JSON                                                     AlertEvent
  ─────────────►  ┌──────────────────┐        ┌──────────────────┐  ─────────────►
                  │                  │ state  │                  │
                  │   SceneState     │───────►│   RulesEngine    │
                  │   scene_state.py │        │   engine.py      │
                  │                  │        │                  │
                  │  summary         │  rules │  evaluate()      │
                  │  objects[]       │◄───────│  check cooldown  │
                  │  people_count    │        │  build AlertEvent│
                  │  change_log:200  │        │  confidence score│
                  │  update_count    │        │                  │
                  └──────────────────┘        └────────┬─────────┘
                                                       │
                  ┌──────────────────┐                 │
                  │  RulesStore      │  YAML            │
                  │  store.py        │─────►(loads)     │
                  │                  │                   │
                  │  ~/.physical-mcp/│        ┌──────────┴─────────┐
                  │    rules.yaml    │        │  Rule Templates    │
                  │  CRUD + persist  │        │  templates.py      │
                  └──────────────────┘        │                    │
                                              │  9 presets:        │
                  ┌──────────────────┐        │  · person_detector │
                  │  WatchRule model  │        │  · package_watch   │
                  │  models.py       │        │  · pet_monitor     │
                  │                  │        │  · parking_monitor  │
                  │  id, name, cond  │        │  · pantry_tracker  │
                  │  priority, notif │        │  · baby_monitor    │
                  │  cooldown, owner │        │  · workspace_guard │
                  │  custom_message  │        │  · weather_watcher │
                  └──────────────────┘        │  · storefront      │
                                              └────────────────────┘


═══ LOGISTICS NETWORK (Notifications) ═════════════════════════════════════════════════════════

  Dispatcher routes each AlertEvent to the right delivery channel.
  Desktop bonus: local popup alongside any remote notification.

                             ┌────────────────────────┐
                 AlertEvent  │                        │
          ──────────────────►│  NotificationDispatcher│
                             │  __init__.py           │
                             │                        │
                             │  Routes by rule's      │
                             │  notification.type     │
                             └───────────┬────────────┘
                                         │
          ┌──────────┬──────────┬────────┼────────┬──────────┬──────────┐
          ▼          ▼          ▼        ▼        ▼          ▼          ▼
     ┌─────────┐┌─────────┐┌─────────┐┌──────┐┌─────────┐┌─────────┐┌─────────┐
     │  📱 TG  ││  💬 DC  ││  💼 SL  ││ 🔔 NT││  🔗 WH  ││  🐙 OC  ││  🖥  DT  │
     │telegram ││discord  ││slack    ││ntfy  ││webhook  ││openclaw ││desktop  │
     │.py      ││.py      ││.py      ││.py   ││.py      ││.py      ││.py      │
     │         ││         ││         ││      ││         ││         ││         │
     │sendPhoto││embed+   ││Block Kit││push  ││JSON POST││CLI sub  ││native   │
     │+caption ││image    ││(text)   ││+image││(generic)││multichan││toast    │
     │aiohttp  ││aiohttp  ││aiohttp  ││aio   ││aiohttp  ││subprocess│macOS/  │
     │Bot API  ││webhooks ││webhooks ││http  ││any URL  ││TG/WA/DC ││Linux/Win│
     └─────────┘└─────────┘└─────────┘└──────┘└─────────┘└─────────┘└─────────┘


═══ POWER PLANT (Orchestration) ════════════════════════════════════════════════════════════════

  The perception loop is the reactor core. One loop per camera, fully async.
  It wires ALL the above together and runs 24/7.

  ┌─────────────────────────────────────────────────────────────────────────────────────────┐
  │                                                                                         │
  │   ⚡ PERCEPTION LOOP — perception/loop.py (557 lines)                                   │
  │                                                                                         │
  │   One async task per camera. The main production line:                                  │
  │                                                                                         │
  │   ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐   │
  │   │ capture │──►│ buffer  │──►│ detect  │──►│ sample? │──►│ analyze │──►│ evaluate│   │
  │   │ frame   │   │ store   │   │ change  │   │ (gate)  │   │ (LLM)   │   │ rules   │   │
  │   └─────────┘   └─────────┘   └─────────┘   └─────────┘   └─────────┘   └────┬────┘   │
  │                                                                                │        │
  │   Dual mode:                                                          triggered? ──►dispatch│
  │   · Server-side: has reasoning provider → calls LLM, evaluates, dispatches              │
  │   · Client-side: no provider → queues PendingAlert for MCP client to poll               │
  │                                                                                         │
  │   Safety:                                                                               │
  │   · No rules = zero API calls                                                           │
  │   · Error backoff: 5s → 10s → 20s → ... → 300s max                                    │
  │   · Health tracking per camera (ok/degraded/offline)                                    │
  │   · Stats: budget tracking, hourly rate limits                                          │
  │                                                                                         │
  └─────────────────────────────────────────────────────────────────────────────────────────┘


═══ TRAIN STATIONS (External APIs) ═════════════════════════════════════════════════════════════

  Two independent servers export the factory's products to the outside world.

  ┌──────────────────────────────────────┐     ┌──────────────────────────────────────┐
  │                                      │     │                                      │
  │  🚂 MCP SERVER · port 8400           │     │  🚂 VISION REST API · port 8090      │
  │     __main__.py (1248 lines)         │     │     vision_api.py (1194 lines)       │
  │     server.py (1266 lines)           │     │                                      │
  │                                      │     │  Endpoints:                          │
  │  Transport: streamable-http          │     │  GET  /scene ····· scene summary     │
  │                                      │     │  GET  /frame ····· latest JPEG       │
  │  MCP Tools:                          │     │  GET  /stream ···· MJPEG live        │
  │  · get_camera_frame()                │     │  GET  /rules ····· list rules        │
  │  · get_scene_analysis()              │     │  POST /rules ····· create rule       │
  │  · watch_for(condition)              │     │  DELETE /rules/:id  remove rule      │
  │  · check_camera_alerts()             │     │  PUT  /rules/:id/toggle              │
  │  · manage_memory()                   │     │  GET  /alerts ···· recent alerts     │
  │                                      │     │  GET  /health ···· server status     │
  │  Clients:                            │     │  GET  /dashboard · web UI (HTML)     │
  │  · Claude Desktop                    │     │  GET  /templates · rule presets      │
  │  · Cursor / VS Code                  │     │  GET  /cameras ·· list cameras       │
  │  · ChatGPT (native MCP)             │     │  GET  /stats ····· cost tracking     │
  │  · Gemini                            │     │                                      │
  │  · OpenClaw                          │     │  Auth: Bearer token                  │
  │                                      │     │  CORS: LAN + Flutter app             │
  └──────────────────────────────────────┘     └──────────────────────────────────────┘


═══ SUPPORT BUILDINGS ══════════════════════════════════════════════════════════════════════════

  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
  │  🔋 StatsTracker │  │  🧠 MemoryStore  │  │  📡 Discovery    │  │  🏥 Health       │
  │     stats.py     │  │     memory.py    │  │     discover.py  │  │     health.py    │
  │                  │  │                  │  │                  │  │                  │
  │  API call count  │  │  Persistent AI   │  │  Subnet scan     │  │  Per-camera      │
  │  Daily budget    │  │  memory file     │  │  RTSP port probe │  │  health state    │
  │  Hourly rate     │  │  (~/.physical-   │  │  ONVIF multicast │  │  ok/degraded/    │
  │  Cost estimate   │  │   mcp/memory.md) │  │  Brand detection │  │  offline         │
  │  Prune window    │  │  Thread-safe     │  │  Async parallel  │  │                  │
  └──────────────────┘  └──────────────────┘  └──────────────────┘  └──────────────────┘

  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
  │  ⚙️  Config       │  │  📋 AlertQueue   │  │  🌐 mDNS        │  │  🔧 Platform     │
  │     config.py    │  │     alert_queue  │  │     mdns.py     │  │     platform.py  │
  │                  │  │     .py          │  │                  │  │                  │
  │  YAML + env vars │  │  PendingAlert    │  │  Zeroconf        │  │  Cross-platform  │
  │  Pydantic valid  │  │  queue for       │  │  auto-discovery  │  │  doctor check    │
  │  ${VAR} interp   │  │  client-side     │  │  _physical-mcp   │  │  QR code gen     │
  │  Nested models   │  │  evaluation mode │  │  .tcp.local.     │  │  IP detection    │
  └──────────────────┘  └──────────────────┘  └──────────────────┘  └──────────────────┘

  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
  │  📸 Snap         │  │  📎 Clipboard    │  │  🚨 Exceptions   │
  │     snap.py      │  │     clipboard.py │  │     exceptions   │
  │                  │  │                  │  │     .py          │
  │  Quick capture   │  │  Copy frame to   │  │                  │
  │  + analyze CLI   │  │  system clip     │  │  Camera errors   │
  │  One-shot mode   │  │  macOS pbcopy    │  │  Timeout errors  │
  └──────────────────┘  └──────────────────┘  │  Config errors   │
                                              └──────────────────┘


═══ PRODUCTION STATS ═══════════════════════════════════════════════════════════════════════════

  Files: 52 Python modules across 6 packages
  Lines: ~8,000 (production) + ~3,000 (tests)
  Tests: 506 passing, CI green on Linux/macOS/Windows × Python 3.10-3.13

  Package breakdown:
  ├── camera/        6 files   Frame extraction (USB, RTSP, buffer, discovery)
  ├── perception/    4 files   Change detection, sampling, scene state, main loop
  ├── reasoning/     7 files   LLM providers (Anthropic, Google, OpenAI-compat)
  ├── rules/         5 files   Watch rules engine, models, templates, YAML store
  ├── notifications/ 8 files   7 delivery channels + dispatcher
  └── (root)        22 files   Config, APIs, CLI, health, memory, platform utils

  Cost model:
  ┌─────────────────────────────────────────────────────────────────┐
  │  Static scene + no rules  →  $0.000/hr  (zero API calls)       │
  │  Active rules + changes   →  ~$0.001/analysis (Gemini Flash)   │
  │  Busy scene, 60/hr        →  ~$0.06/hr  (~$1.44/day)          │
  │  Daily budget cap          →  configurable, hard stop           │
  └─────────────────────────────────────────────────────────────────┘
```

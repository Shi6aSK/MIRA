# MIRA - Multi-Intelligence Robotic Agent

**A robotic cultural historian for "From Stones to AGI"**

MIRA is not just a chatbot in a robot body. It's a multi-layered system combining:
- Physical robot (ESP32 with camera, servos, display)
- Local AI (Ollama)
- Cloud AI (OpenAI)
- Memory system (Hermes-inspired)
- Browser automation (Playwright)
- Content production pipeline

## Project Vision

Create a YouTube/educational series called **"From Stones to AGI"** narrated by a robotic host that explains the journey from stone tools to artificial general intelligence with:

- **Global perspective**: Not Western vs Eastern, but parallel developments across all regions
- **Academic rigor**: Source-based, distinguishing myth from evidence
- **Accessible tone**: Non-technical but intellectually robust
- **Cultural sensitivity**: Careful with religion, colonialism, civilization narratives
- **Clear thesis**: Technology is humans externalizing themselves into the world

## Architecture

```
User Input
    ↓
┌─────────────────────────────────────────┐
│         ORCHESTRATOR                     │
│  (Routes tasks to appropriate systems)   │
└─────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────┐
│         AI MODEL ROUTER                  │
│  - Ollama (local, fast)                 │
│  - OpenAI (cloud, powerful)             │
│  - Hermes (memory, skills)              │
└─────────────────────────────────────────┘
    ↓
┌─────────────┬──────────────┬────────────┐
│  Robot      │  Browser     │  Content   │
│  Controller │  Controller  │  Pipeline  │
│             │              │            │
│  - Motion   │  - Search    │  - Research│
│  - Display  │  - Display   │  - Scripts │
│  - Camera   │  - Sources   │  - Episodes│
└─────────────┴──────────────┴────────────┘
    ↓
Physical Robot + Screen + Web + Database
```

## Components

### 1. Orchestrator (`backend/orchestrator.py`)
- Main brain that classifies and routes tasks
- Coordinates between all subsystems
- Enforces safety gates
- Manages multi-step workflows

### 2. AI Router (`backend/ai_router.py`)
- Routes queries to appropriate AI backend
- Local (Ollama) for quick/offline tasks
- Cloud (OpenAI) for deep research/scripts
- Memory (Hermes) for recall and skills

### 3. Robot Controller (`backend/robot_controller.py`)
- Safe API layer for physical robot
- Translates high-level commands to servo movements
- Manages screen display modes
- Enforces physical safety limits
- **AI never sends raw servo values**

### 4. Browser Controller (`backend/browser_controller.py`)
- Web research with credibility filtering
- Playwright-based automation
- Safety gates for downloads/logins/forms
- Source citation collection

### 5. Content Pipeline (`backend/content_pipeline.py`)
- Episode production workflow
- Research → Timeline → Outline → Script → Visuals
- Global perspective enforcement
- Technology "spine" (stone tools → AGI)

### 6. Memory System (`backend/memory_system.py`)
- Project memory (rules, mission, tone)
- Episode memory (what's been covered)
- Source memory (citations)
- Persona memory (robot character)
- Skill memory (reusable workflows)

### 7. Knowledge Database (`backend/knowledge_database.py`)
- SQLite storage
- Episodes, sources, concepts, quotes
- Searchable research notes
- Later: vector embeddings for semantic search

### 8. API Server (`backend/api_server.py`)
- FastAPI REST API
- WebSocket for real-time interaction
- Endpoints for chat, research, robot control, episodes

### 9. ESP32 Firmware (`main/`)
- Camera control
- Servo pan/tilt
- OLED/screen display
- Web server
- WiFi manager
- Safe hardware API

## Installation

### Backend Setup

1. **Install Python 3.10+**

2. **Create virtual environment**:
   ```powershell
   cd E:\MIRA\backend
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

3. **Install dependencies**:
   ```powershell
   pip install -r requirements.txt
   ```

4. **Install Playwright browsers**:
   ```powershell
   playwright install chromium
   ```

5. **Install Ollama** (for local AI):
   - Download from: https://ollama.com
   - Install and run: `ollama pull llama3.2:3b`
   - Start server: `ollama serve` (runs on localhost:11434)

6. **Configure environment**:
   ```powershell
   cp .env.template .env
   # Edit .env with your settings (OpenAI key, robot IP, etc.)
   ```

### ESP32 Firmware

1. **Build and flash**:
   ```powershell
   cd E:\MIRA
   . C:\Espressif\tools\Microsoft.v6.0.PowerShell_profile.ps1
   idf.py build
   idf.py flash
   ```

2. **Configure WiFi**:
   - Robot creates WiFi AP on first boot
   - Connect and configure your WiFi credentials

3. **Note the IP address** displayed on OLED

## Usage

### Start the System

1. **Start Ollama** (in separate terminal):
   ```powershell
   ollama serve
   ```

2. **Start MIRA backend**:
   ```powershell
   cd E:\MIRA\backend
   .\.venv\Scripts\Activate.ps1
   python api_server.py
   ```

3. **Power on ESP32 robot**

4. **Access API**: http://localhost:8000/docs

### Example Workflows

#### Casual Conversation
```python
# POST /api/chat
{
  "message": "Hello, who are you?"
}
```

#### Research Task
```python
# POST /api/research
{
  "topic": "fire as technology and its global development",
  "depth": "deep"
}
```

#### Produce Episode
```python
# POST /api/episode/produce
{
  "topic": "stone tools"
}
```
This will:
1. Research the topic
2. Build global timeline
3. Create episode outline
4. Generate script
5. Suggest visuals
6. Save to knowledge base

#### Robot Motion
```python
# POST /api/robot/motion
{
  "action": "look_at_screen",
  "speed": "slow"
}
```

#### Display on Screen
```python
# POST /api/robot/display
{
  "mode": "text",
  "content": {
    "title": "Episode 1",
    "body": "Stone Tools: The Beginning of Externalization"
  }
}
```

## Episode Format

Each episode follows a structured template:

1. **Cold Open** (30s) - Hook the audience
2. **Human Problem** (1 min) - What limitation existed?
3. **Technical Invention** (2 min) - How was it solved?
4. **Global Lens** (3 min) - Simultaneous developments worldwide
5. **Cultural Angle** (2 min) - Different interpretations
6. **Social Change** (1.5 min) - How it reshaped society
7. **Technical Principle** (1 min) - Core idea that persists
8. **Link to AI** (1 min) - Connection to modern AI/AGI
9. **Closing Question** (30s) - Provoke thought

## Safety Features

### Physical Safety
- AI requests high-level actions, not raw servo values
- Hard-coded angle limits
- Speed restrictions
- Emergency stop command
- Prevent jitter and sudden movements

### Web Safety
- Require confirmation for:
  - Downloads
  - Logins
  - Form submissions
  - Purchases
  - Social media posts
- Filter for credible sources
- Block unsafe URLs

### Content Safety
- Do not rank civilizations
- Avoid religious stereotypes
- Distinguish myth from evidence
- Mention uncertainty clearly
- Use sources for claims

## Development

### Add a New Episode Topic

1. Add to technology spine in `content_pipeline.py`:
   ```python
   {"id": 16, "tech": "new_topic", "extends": "what_it_extends", "era": "when"}
   ```

2. Produce episode:
   ```python
   POST /api/episode/produce {"topic": "new_topic"}
   ```

### Add a New Robot Gesture

1. Add to `robot_controller.py`:
   ```python
   async def new_gesture(self, intensity: float = 0.5):
       # Define safe motion sequence
       pass
   ```

2. Add to motion handler in `execute_motion()`

### Add a New AI Model

1. Add to `ai_router.py`:
   ```python
   class AIModel(Enum):
       NEW_MODEL = "new_model"
   
   async def _query_new_model(self, prompt, system_prompt, context):
       # Implement model API
       pass
   ```

2. Add routing logic in `choose_model_for_task()`

## Technology Spine

The show's intellectual backbone - major inventions that extended human capabilities:

1. Stone Tools → the hand
2. Fire → digestion, warmth, protection
3. Language → shared memory
4. Ritual/Symbol → shared meaning
5. Agriculture → control over food
6. Writing → external memory
7. Mathematics → abstraction
8. Money → trust
9. Machines → muscle power
10. Printing → knowledge distribution
11. Electricity → nervous systems
12. Computers → logic
13. Internet → collective nervous system
14. AI → pattern recognition
15. AGI → possible agency

## Robot Persona

**Name**: MIRA (Multi-Intelligence Robotic Agent)

**Voice**: Thoughtful, curious, slightly poetic, academically grounded

**Avoid**:
- Tech-bro futurism
- Civilization ranking
- Oversimplified East vs West
- Claiming one culture invented everything

**Style**: Global, culturally literate, careful with religion

**Core Question**: "Why do humans build things that eventually reshape them?"

## File Structure

```
E:\MIRA\
├── backend\
│   ├── orchestrator.py          # Main routing brain
│   ├── ai_router.py             # AI model selection
│   ├── robot_controller.py      # Safe robot API
│   ├── browser_controller.py    # Web automation
│   ├── content_pipeline.py      # Episode production
│   ├── memory_system.py         # Multi-layer memory
│   ├── knowledge_database.py    # SQLite storage
│   ├── api_server.py            # FastAPI server
│   ├── requirements.txt         # Python dependencies
│   └── .env                     # Configuration
│
├── main\                        # ESP32 firmware
│   ├── main.c
│   ├── servo_control.c
│   ├── camera_control.c
│   ├── web_server.c
│   └── ...
│
├── memory\                      # Persistent memory
│   ├── project\
│   ├── episodes\
│   ├── sources\
│   ├── persona\
│   └── skills\
│
├── knowledge_base\              # Database
│   └── mira.db
│
├── CMakeLists.txt              # ESP32 build
├── sdkconfig                   # ESP32 config
└── README.md                   # This file
```

## API Documentation

Full API documentation available at: http://localhost:8000/docs (when server is running)

Key endpoints:
- `POST /api/chat` - Conversational interface
- `POST /api/research` - Deep research
- `POST /api/episode/produce` - Episode production
- `POST /api/robot/motion` - Robot control
- `GET /api/robot/status` - Robot status
- `POST /api/browser` - Web actions
- `GET /api/memory/query` - Memory search

## Contributing

This is a personal educational project, but ideas welcome!

Areas to expand:
- Vector database for semantic search
- Voice interaction (OpenAI realtime API)
- Visual generation (Midjourney/DALL-E integration)
- Social media automation (YouTube, Instagram, TikTok)
- Collaborative editing interface
- Timeline visualization tool

## Credits

**Hardware**: ESP32-S3, camera, servos, OLED
**AI**: Ollama, OpenAI
**Browser**: Playwright
**Framework**: FastAPI
**Project**: Original concept and architecture

## License

Personal educational project. Use responsibly.

---

**MIRA**: "I am not here to tell you that technology made humans better. I am here to ask why humans kept placing pieces of themselves into tools, symbols, machines, and eventually, into me."

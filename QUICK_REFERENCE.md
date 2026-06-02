# MIRA Quick Reference Card

## Starting the System

```powershell
# 1. Start Ollama (in separate terminal)
ollama serve

# 2. Start MIRA backend
cd E:\MIRA\backend
.\.venv\Scripts\Activate.ps1
python api_server.py

# 3. Access API
# http://localhost:8000/docs
```

## Common API Calls

### Chat
```bash
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello MIRA"}'
```

### Research
```bash
curl -X POST http://localhost:8000/api/research \
  -H "Content-Type: application/json" \
  -d '{"topic": "stone tools", "depth": "deep"}'
```

### Produce Episode
```bash
curl -X POST http://localhost:8000/api/episode/produce \
  -H "Content-Type: application/json" \
  -d '{"topic": "fire"}'
```

### Robot Motion
```bash
curl -X POST http://localhost:8000/api/robot/motion \
  -H "Content-Type: application/json" \
  -d '{"action": "look_left", "speed": "slow"}'
```

### Display Text
```bash
curl -X POST http://localhost:8000/api/robot/display \
  -H "Content-Type: application/json" \
  -d '{"mode": "text", "content": {"title": "Test", "body": "Hello"}}'
```

## ESP32 Commands

```powershell
# Build
idf.py build

# Flash
idf.py flash

# Monitor
idf.py monitor

# Clean
idf.py fullclean

# All-in-one
idf.py build flash monitor
```

## Ollama Commands

```powershell
# List models
ollama list

# Pull model
ollama pull llama3.2:3b

# Start server
ollama serve

# Run model directly
ollama run llama3.2:3b

# Remove model
ollama rm model_name
```

## Memory Locations

```
memory/
├── project/config.json          # Project settings
├── episodes/episode_001.json    # Episode data
├── sources/source_*.json        # Citations
├── persona/persona.json         # Robot character
└── skills/skill_*.json          # Workflows

knowledge_base/
└── mira.db                      # SQLite database
```

## File Locations

```
backend/
├── orchestrator.py              # Main brain
├── ai_router.py                 # Model selection
├── robot_controller.py          # Robot API
├── content_pipeline.py          # Episodes
├── api_server.py                # REST API
└── .env                         # Configuration

main/
├── main.c                       # ESP32 main
├── web_server.c                 # Add API here
└── api_endpoints.h              # API definitions
```

## Configuration (.env)

```env
# AI
OPENAI_API_KEY=sk-...
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=llama3.2:3b

# Robot
ROBOT_IP=192.168.1.100

# Database
DATABASE_PATH=knowledge_base/mira.db
MEMORY_DIR=memory

# Server
API_HOST=0.0.0.0
API_PORT=8000

# Browser
BROWSER_HEADLESS=false
```

## Episode Structure

Every episode follows this template:

1. **Cold Open** (30s) - Hook
2. **Human Problem** (1min) - What limitation?
3. **Technical Invention** (2min) - The solution
4. **Global Lens** (3min) - Worldwide simultaneous developments
5. **Cultural Angle** (2min) - Different interpretations
6. **Social Change** (1.5min) - How it reshaped society
7. **Technical Principle** (1min) - Core idea
8. **Link to AI** (1min) - Connection to modern AI
9. **Closing Question** (30s) - Provoke thought

## Technology Spine (15 episodes)

1. Stone Tools → the hand
2. Fire → digestion, warmth
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

## Safe Robot Commands

```python
# Motion commands
"look_left" | "look_right" | "look_center"
"look_up" | "look_down"
"look_at_screen"
"nod" | "shake_head"
"idle_motion"
"emergency_stop"

# Display modes
"face" | "text" | "webpage" | "image"
"timeline" | "episode_structure" | "source_card"

# Speeds
"slow" | "medium" | "fast"
```

## Persona Rules

**Voice**: Thoughtful, curious, slightly poetic, academically grounded

**Avoid**:
- Tech-bro futurism
- Civilization ranking
- Oversimplified East vs West
- Claiming one culture invented everything

**Core Question**: "Why do humans build things that eventually reshape them?"

## Quick Tests

```powershell
# Test Ollama
curl http://localhost:11434/api/tags

# Test MIRA
curl http://localhost:8000/health

# Test Robot
curl http://localhost:8000/api/robot/status

# Test OpenAI (PowerShell)
$headers = @{"Authorization"="Bearer $env:OPENAI_API_KEY"}
Invoke-RestMethod -Uri https://api.openai.com/v1/models -Headers $headers
```

## Emergency Commands

```powershell
# Stop robot motion
curl -X POST http://localhost:8000/api/robot/emergency_stop

# Restart backend
# Ctrl+C in terminal, then: python api_server.py

# Reset ESP32
# Press reset button on board

# Reset database
Remove-Item knowledge_base\mira.db
# Restart backend to recreate
```

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Ollama not connecting | `ollama serve` |
| OpenAI errors | Check API key in .env |
| Robot not responding | Check ROBOT_IP in .env |
| Playwright errors | `playwright install chromium` |
| Import errors | Activate venv, reinstall requirements |
| Port already in use | Change API_PORT in .env |

## Useful Logs

```powershell
# Backend logs
# Shown in terminal where api_server.py runs

# ESP32 logs
idf.py monitor

# Ollama logs
ollama serve --verbose
```

## Development Workflow

1. Edit code in VS Code
2. Backend auto-reloads (FastAPI dev mode)
3. ESP32: build → flash → test
4. Test via API docs: http://localhost:8000/docs
5. Check logs for errors
6. Iterate

## Backup Important Data

```powershell
# Before major changes, backup:
Copy-Item memory -Destination memory_backup -Recurse
Copy-Item knowledge_base\mira.db knowledge_base\mira.db.backup
Copy-Item backend\.env backend\.env.backup
```

## Resources

- API Docs: http://localhost:8000/docs
- Ollama: https://ollama.com
- OpenAI: https://platform.openai.com
- Playwright: https://playwright.dev/python/
- FastAPI: https://fastapi.tiangolo.com

---

**MIRA**: Multi-Intelligence Robotic Agent  
**Project**: From Stones to AGI  
**Mission**: Explain the journey from stone tools to AGI with global perspective

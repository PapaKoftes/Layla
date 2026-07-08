# Layla Distributed Deployment Guide

Step-by-step instructions for deploying Layla across multiple machines:
one **QUEEN** (desktop) and one or more **DRONE** workers (laptops).

---

## Prerequisites

- **Windows 10/11** on all machines
- **Python 3.11 or 3.12** installed and on PATH (`requires-python = ">=3.11,<3.13"`)
- **Git** (recommended for updates)
- **Tailscale** installed on all machines (for cross-network mesh VPN)
- All machines on the same Tailscale network (or same LAN for mDNS discovery)

---

## 1. Install the QUEEN Node (Desktop)

### 1a. Clone and run the installer

```powershell
git clone <repo-url> C:\layla
cd C:\layla
.\install.bat
```

The installer runs `install.ps1`, which:
- Creates a Python virtual environment
- Installs dependencies from `requirements.txt`
- Launches the **Setup Wizard** (`agent/install/setup_wizard.py`)

### 1b. Setup Wizard

The wizard walks through 8 steps:

1. **Purpose selection** - Choose your use case (personal assistant, software dev, research, etc.)
2. **Hardware probe** - Auto-detects CPU, RAM, GPU, and available disk
3. **Location choice** - Where to store Layla's data (defaults to `~/.layla/`)
4. **Model selection** - Recommends a GGUF model based on your hardware tier
5. **Node role** - Select **QUEEN** for the primary desktop
6. **Cluster setup** - Enable clustering (optional at this stage)
7. **Service install** - Install as a Windows Service via NSSM
8. **Verification** - Confirms all components are working

### 1c. Install as Windows Service (recommended)

If you didn't install the service during the wizard:

```powershell
cd C:\layla\agent\install
.\install_service.ps1
```

This registers Layla as `LaylaSvc` via NSSM:
- Starts automatically at boot
- Restarts on crash (10-second delay)
- Runs at Below Normal priority
- Logs to `agent/logs/service.log`

### 1d. Verify the QUEEN

```powershell
# Check service status
nssm status LaylaSvc

# Or check the API directly
curl http://127.0.0.1:8000/health
```

Open `http://127.0.0.1:8000` in your browser. You should see the Layla UI.

---

## 2. Configure Tailscale (All Machines)

### 2a. Install Tailscale

Download from [tailscale.com](https://tailscale.com/) and install on all machines.

### 2b. Connect all machines

```powershell
# On each machine:
tailscale up
```

### 2c. Verify connectivity

```powershell
# On the QUEEN, find your Tailscale IP:
tailscale ip

# On a DRONE, verify it can reach the QUEEN:
ping <queen-tailscale-ip>
```

Note the QUEEN's Tailscale IP. You'll need it for DRONE pairing.

---

## 3. Install DRONE Nodes (Laptops)

### 3a. Clone and run the installer

```powershell
git clone <repo-url> C:\layla
cd C:\layla
.\install.bat
```

### 3b. Setup Wizard for DRONE

Follow the same wizard, but at step 5:
- Select **DRONE** as the node role
- When asked, enter the QUEEN's address (Tailscale IP or LAN IP)
- Enter the pairing token from the QUEEN

### 3c. Generate pairing token on QUEEN

On the QUEEN, either:

**Via the UI:** Open the Cluster tab, click "Generate Pairing Token"

**Via API:**
```powershell
curl http://127.0.0.1:8000/cluster/pair/token
```

The token is valid for 10 minutes.

### 3d. Pair the DRONE

During the DRONE setup wizard, enter the pairing token when prompted.
The DRONE will:
1. Contact the QUEEN at the provided address
2. Exchange the pairing token for a cluster secret
3. Register itself as a peer in the QUEEN's cluster config
4. Begin heartbeat communication

### 3e. Install DRONE as service (optional)

For always-on DRONEs (e.g., a laptop that stays at home):

```powershell
cd C:\layla\agent\install
.\install_service.ps1
```

For portable DRONEs that are only sometimes connected, manual start may be
preferable.

---

## 4. Verify the Cluster

### 4a. Check cluster status on QUEEN

```powershell
curl http://127.0.0.1:8000/cluster/status
```

Expected response includes:
- `cluster_enabled: true`
- `node_role: "queen"`
- Connected peers listed

### 4b. Check peer list

```powershell
curl http://127.0.0.1:8000/cluster/peers
```

All paired DRONEs should appear with status `"online"`.

### 4c. Verify in the UI

Open the QUEEN's web UI and click the **Cluster** tab:
- Your QUEEN should appear as "self" with a green dot
- Each DRONE should appear with its name, role, and status
- The governor mode (WHISPER/BREATHE/SPRINT) should reflect your current
  activity level

### 4d. Test task distribution

Submit a test task via API:
```powershell
curl -X POST http://127.0.0.1:8000/cluster/task/submit `
  -H "Content-Type: application/json" `
  -d '{"type": "embedding", "payload": {"text": "test embedding"}}'
```

Check task status to confirm it was dispatched to a DRONE.

---

## 5. Resource Governor

The governor automatically manages resource consumption:

| Mode | When | CPU Cap | Workers | Background Tasks |
|------|------|---------|---------|-----------------|
| WHISPER | User typing/clicking | 5% | 1 | Paused |
| BREATHE | Light activity | 25% | 2 | High-priority only |
| SPRINT | Idle 10+ minutes | 80% | Max | All tasks run |

The governor checks every 15 seconds using Windows `GetLastInputInfo`.
No manual configuration is needed - it responds automatically.

### Override via config

Edit `runtime_config.json` to adjust thresholds:

```json
{
  "whisper_cpu_cap": 0.05,
  "breathe_cpu_cap": 0.25,
  "sprint_cpu_cap": 0.80,
  "whisper_timeout_seconds": 60,
  "sprint_timeout_seconds": 600
}
```

---

## 6. Knowledge Growth

### 6a. Knowledge File Watcher

Configure folders to watch during onboarding, or edit `runtime_config.json`:

```json
{
  "watch_folders": ["C:\\Users\\you\\Documents\\Knowledge"],
  "exclude_folders": ["node_modules", ".git", "__pycache__"]
}
```

Supported file types: `.pdf`, `.docx`, `.txt`, `.md`, `.py`, `.json`,
`.yaml`, `.csv`, `.html`, `.xml`, `.rst`, `.tex`, `.log`, `.ini`, `.cfg`,
`.toml`, `.env`, `.bat`, `.ps1`, `.sh`, `.sql`, `.r`, `.m`, `.ipynb`,
`.epub`

The watcher only processes files when in BREATHE or SPRINT mode.

### 6b. Verification Queue

Layla periodically asks you to verify facts she's learned:
- Max 3 verification prompts per session
- 24-hour cooldown between re-asks
- High-importance facts are prioritised
- Confirmed facts get confidence boosted to 1.0
- Rejected facts can be corrected inline

Check verification status in the **Growth** tab of the UI.

---

## 7. Managing the Service

### Start / Stop / Restart

```powershell
nssm start LaylaSvc
nssm stop LaylaSvc
nssm restart LaylaSvc
```

### View logs

```powershell
Get-Content C:\layla\agent\logs\service.log -Tail 50 -Wait
```

### Uninstall

```powershell
cd C:\layla
.\uninstall.bat
```

The uninstaller:
1. Stops all running services
2. Asks what to keep (models, data, knowledge base)
3. Removes the NSSM service
4. Cleans up the virtual environment
5. Removes scheduled tasks and launcher scripts

---

## 8. Troubleshooting

### QUEEN won't start

```powershell
# Check service status
nssm status LaylaSvc

# Check logs for errors
Get-Content C:\layla\agent\logs\service.log -Tail 100

# Try running directly to see errors
cd C:\layla\agent
..\venv\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8000
```

### DRONE can't connect to QUEEN

1. Verify Tailscale is running on both machines: `tailscale status`
2. Verify the QUEEN's IP is reachable: `ping <queen-ip>`
3. Verify the QUEEN's API is accessible: `curl http://<queen-ip>:8000/health`
4. Check firewall rules: port 8000 must be open for Tailscale interface
5. Check the DRONE's logs for connection errors

### Pairing fails

- Tokens expire after 10 minutes. Generate a fresh one.
- Ensure the DRONE can reach the QUEEN's API endpoint.
- Check that `cluster_enabled` is `true` in the QUEEN's config.

### mDNS discovery not finding peers

- Both machines must be on the same LAN subnet
- Windows Firewall must allow mDNS (UDP port 5353)
- Try Tailscale-based discovery instead (automatic if both are on Tailscale)

### High CPU when user is active

- Check governor mode: `curl http://127.0.0.1:8000/cluster/status`
- If stuck in SPRINT, the idle detector may not be reading input correctly
- Verify `GetLastInputInfo` works: governor logs show idle seconds
- Reduce `whisper_cpu_cap` in config if needed

### Knowledge watcher not processing files

- Watcher only runs in BREATHE or SPRINT mode
- Check that `watch_folders` is configured in runtime config
- Verify the folder path exists and is accessible
- Check logs for ingestion errors

### Sync not working between nodes

- Verify both nodes show as "online" in cluster status
- Check `cluster_sync_interval` in config (default: 300 seconds)
- Manual sync: `curl -X POST http://127.0.0.1:8000/cluster/sync/push`
- Offline buffer: check `pending_sync` table in the DRONE's database

---

## Architecture Overview

```
         QUEEN (Desktop)                    DRONE (Laptop)
    +------------------------+         +------------------------+
    |  Layla Core Engine     |         |  Drone Worker          |
    |  - Agent Loop          |  HTTP   |  - Task Executor       |
    |  - Memory (SQLite+VDB) |<------->|  - Local Memory Cache  |
    |  - Scheduler           |  Sync   |  - Offline Buffer      |
    |  - Task Dispatcher     |         |  - Governor (local)    |
    |  - Resource Governor   |         +------------------------+
    |  - Knowledge Watcher   |
    |  - Web UI              |         +------------------------+
    |  - Cluster Network     |  HTTP   |  DRONE-GO (Portable)   |
    +------------------------+<------->|  - Same as above       |
              |                  Sync   |  - Offline mode        |
              |                         +------------------------+
         Tailscale Mesh VPN
         (or LAN + mDNS)
```

**Task flow:**
1. Task enters the QUEEN's dispatcher
2. Dispatcher checks governor mode + drone availability
3. WHISPER: offload to drones. SPRINT: prefer local. BREATHE: split by type.
4. Results sync back via the cluster network
5. Knowledge is deduplicated by content hash on merge

---

## Configuration Reference

All config keys go in `runtime_config.json` (QUEEN) or are set via the
Setup Wizard.

| Key | Default | Description |
|-----|---------|-------------|
| `resource_governor_enabled` | `true` | Enable 3-mode governor |
| `whisper_cpu_cap` | `0.05` | CPU cap in WHISPER mode |
| `breathe_cpu_cap` | `0.25` | CPU cap in BREATHE mode |
| `sprint_cpu_cap` | `0.80` | CPU cap in SPRINT mode |
| `whisper_timeout_seconds` | `60` | Seconds before WHISPER->BREATHE |
| `sprint_timeout_seconds` | `600` | Seconds idle before SPRINT |
| `governor_tick_seconds` | `15` | Governor update interval |
| `cluster_enabled` | `false` | Enable multi-node clustering |
| `node_role` | `"queen"` | This node's role |
| `cluster_heartbeat_interval` | `30` | Heartbeat interval (seconds) |
| `cluster_task_timeout` | `300` | Task timeout (seconds) |
| `cluster_sync_interval` | `300` | Knowledge sync interval (seconds) |
| `system_tray_enabled` | `true` | Show system tray icon |
| `scheduler_study_enabled` | `true` | Enable background study |
| `scheduler_interval_minutes` | `30` | Study job interval |

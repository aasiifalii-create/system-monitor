# System Monitor - Real-Time Infrastructure Monitoring

An independent monitoring system that collects metrics from devices and displays them on the dashboard.

## Architecture

```
┌─────────────────────┐     HTTP POST      ┌──────────────────┐     HTTP GET      ┌────────────────┐
│   Monitor Client    │ ─────────────────► │   Metrics API    │ ◄──────────────── │    Frontend    │
│  (monitor_client.py)│   /api/metrics/    │  (metrics_api.py)│   /api/metrics/   │   (Home.js)    │
│                     │      ingest        │   Port 5001      │      latest       │   Port 3000    │
│  • psutil (local)   │                    │                  │                   │                │
│  • pysnmp (SNMP)    │                    │  In-Memory Store │                   │  System Status │
└─────────────────────┘                    └──────────────────┘                   └────────────────┘
```

## Quick Start (3 Steps)

### Step 1: Start the Metrics API Server

```powershell
cd system-monitor
pip install flask flask-cors
python metrics_api.py
```

Server starts at `http://localhost:5001`

### Step 2: Start the Monitor Client

```powershell
# In a new terminal
cd system-monitor
pip install -r requirements.txt
python monitor_client.py --backend http://localhost:5001/api/metrics/ingest
```

### Step 3: Start the React Frontend

```powershell
cd ..
npm start
```

Visit `http://localhost:3000` - The **System Status** section will show real-time data!

## Command Line Options

| Option | Default | Description |
|--------|---------|-------------|
| `--backend` | `http://localhost:5001/api/metrics/ingest` | Backend API endpoint |
| `--device-id` | Hostname | Unique device identifier |
| `--interval` | `5` | Seconds between updates |
| `--once` | False | Send once and exit |
| `--snmp` | False | Use SNMP mode |
| `--host` | `localhost` | SNMP target host |
| `--community` | `public` | SNMP community string |

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/metrics/ingest` | POST | Receive metrics from client |
| `/api/metrics/latest` | GET | Dashboard data (aggregated) |
| `/api/metrics/devices` | GET | List all monitored devices |
| `/api/metrics/device/<id>` | GET | Specific device details |

## Files

| File | Description |
|------|-------------|
| `monitor_client.py` | Independent monitoring agent |
| `metrics_api.py` | Flask API server |
| `requirements.txt` | Python dependencies |

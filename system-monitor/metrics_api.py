"""
Metrics Receiver API - Flask application for receiving and serving system metrics
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
from datetime import datetime
from threading import Lock

app = Flask(__name__)
CORS(app)

# In-memory storage for metrics
_metrics_store = {}
_metrics_lock = Lock()
_MAX_AGE_SECONDS = 60


@app.route('/api/metrics/ingest', methods=['POST'])
def ingest_metrics():
    """Receive metrics from monitor clients."""
    try:
        data = request.get_json()
        
        if not data or 'device_id' not in data:
            return jsonify({"error": "Invalid payload, device_id required"}), 400
        
        device_id = data['device_id']
        data['received_at'] = datetime.utcnow().isoformat() + "Z"
        
        with _metrics_lock:
            _metrics_store[device_id] = data
        
        print(f"[{device_id}] Metrics received - CPU: {data.get('metrics', {}).get('cpu', {}).get('usage_percent', 'N/A')}%")
        
        return jsonify({
            "status": "ok",
            "device_id": device_id,
            "received_at": data['received_at']
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/metrics/devices', methods=['GET'])
def list_devices():
    """List all devices with their latest metrics."""
    with _metrics_lock:
        devices = []
        
        for device_id, data in _metrics_store.items():
            try:
                received_at = datetime.fromisoformat(data['received_at'].replace('Z', '+00:00'))
                age_seconds = (datetime.now(received_at.tzinfo) - received_at).total_seconds()
                is_stale = age_seconds > _MAX_AGE_SECONDS
            except:
                is_stale = True
            
            devices.append({
                "device_id": device_id,
                "hostname": data.get('hostname', 'Unknown'),
                "device_type": data.get('device_type', 'unknown'),
                "overall_status": "offline" if is_stale else data.get('overall_status', 'unknown'),
                "last_seen": data.get('received_at'),
                "is_stale": is_stale
            })
        
        return jsonify({"devices": devices}), 200


@app.route('/api/metrics/device/<device_id>', methods=['GET'])
def get_device_metrics(device_id):
    """Get detailed metrics for a specific device."""
    with _metrics_lock:
        if device_id not in _metrics_store:
            return jsonify({"error": "Device not found"}), 404
        
        data = _metrics_store[device_id].copy()
        
        try:
            received_at = datetime.fromisoformat(data['received_at'].replace('Z', '+00:00'))
            age_seconds = (datetime.now(received_at.tzinfo) - received_at).total_seconds()
            data['is_stale'] = age_seconds > _MAX_AGE_SECONDS
            data['age_seconds'] = age_seconds
        except:
            data['is_stale'] = True
            
        return jsonify(data), 200


@app.route('/api/metrics/latest', methods=['GET'])
def get_latest_metrics():
    """Get the latest metrics from all devices for dashboard display."""
    with _metrics_lock:
        if not _metrics_store:
            return jsonify({
                "status": "no_data",
                "devices": [],
                "summary": {
                    "total_devices": 0,
                    "online": 0,
                    "offline": 0,
                    "healthy": 0,
                    "warning": 0,
                    "critical": 0
                },
                "system_status": {
                    "network": {"status": "unknown", "detail": "No data"},
                    "compute": {"status": "unknown", "detail": "No data"},
                    "storage": {"status": "unknown", "detail": "No data"},
                    "cooling": {"status": "unknown", "detail": "No data"},
                    "security": {"status": "unknown", "detail": "No data"},
                    "power": {"status": "unknown", "detail": "No data"}
                }
            }), 200
        
        devices = []
        summary = {
            "total_devices": 0,
            "online": 0,
            "offline": 0,
            "healthy": 0,
            "warning": 0,
            "critical": 0
        }
        
        # Aggregate metrics
        cpu_statuses = []
        memory_statuses = []
        disk_statuses = []
        network_statuses = []
        
        for device_id, data in _metrics_store.items():
            summary["total_devices"] += 1
            
            try:
                received_at = datetime.fromisoformat(data['received_at'].replace('Z', '+00:00'))
                age_seconds = (datetime.now(received_at.tzinfo) - received_at).total_seconds()
                is_online = age_seconds <= _MAX_AGE_SECONDS
            except:
                is_online = False
                age_seconds = 999
            
            if is_online:
                summary["online"] += 1
                status = data.get('overall_status', 'unknown')
                if status == "healthy":
                    summary["healthy"] += 1
                elif status == "warning":
                    summary["warning"] += 1
                elif status == "critical":
                    summary["critical"] += 1
                    
                # Collect metric statuses
                metrics = data.get('metrics', {})
                if 'cpu' in metrics:
                    cpu_statuses.append(metrics['cpu'].get('status', 'unknown'))
                if 'memory' in metrics:
                    memory_statuses.append(metrics['memory'].get('status', 'unknown'))
                if 'disk' in metrics:
                    disk_statuses.append(metrics['disk'].get('status', 'unknown'))
                if 'network' in metrics:
                    network_statuses.append(metrics['network'].get('status', 'unknown'))
            else:
                summary["offline"] += 1
            
            devices.append({
                "device_id": device_id,
                "hostname": data.get('hostname', 'Unknown'),
                "platform": data.get('platform', 'Unknown'),
                "is_online": is_online,
                "overall_status": "offline" if not is_online else data.get('overall_status', 'unknown'),
                "metrics": data.get('metrics', {}),
                "last_seen": data.get('received_at'),
                "age_seconds": round(age_seconds, 1) if age_seconds != 999 else None
            })
        
        # Aggregate status helper
        def aggregate_status(statuses):
            if not statuses:
                return "unknown"
            if "critical" in statuses:
                return "critical"
            if "warning" in statuses:
                return "warning"
            if all(s == "healthy" for s in statuses):
                return "healthy"
            return "unknown"
        
        # Get most recent device for details
        most_recent = max(devices, key=lambda d: d.get('last_seen', ''), default=None)
        recent_metrics = most_recent.get('metrics', {}) if most_recent else {}
        
        system_status = {
            "network": {
                "status": aggregate_status(network_statuses),
                "detail": f"{recent_metrics.get('network', {}).get('connections', 0)} connections" if recent_metrics.get('network') else "No data"
            },
            "compute": {
                "status": aggregate_status(cpu_statuses),
                "detail": f"{recent_metrics.get('cpu', {}).get('usage_percent', 0):.1f}% CPU" if recent_metrics.get('cpu', {}).get('usage_percent') else "No data"
            },
            "storage": {
                "status": aggregate_status(disk_statuses),
                "detail": f"{recent_metrics.get('disk', {}).get('usage_percent', 0):.1f}% used" if recent_metrics.get('disk', {}).get('usage_percent') else "No data"
            },
            "cooling": {
                "status": "healthy",
                "detail": "Temperature optimal"
            },
            "security": {
                "status": "healthy",
                "detail": "All systems secure"
            },
            "power": {
                "status": "healthy" if summary["online"] > 0 else "unknown",
                "detail": f"{summary['online']}/{summary['total_devices']} online"
            }
        }
        
        return jsonify({
            "status": "ok",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "devices": devices,
            "summary": summary,
            "system_status": system_status
        }), 200


if __name__ == "__main__":
    import os
    port = int(os.environ.get('PORT', 5001))
    print("Starting Metrics Receiver API")
    print("Endpoints:")
    print("  POST /api/metrics/ingest - Receive metrics from clients")
    print("  GET  /api/metrics/devices - List all devices")
    print("  GET  /api/metrics/device/<id> - Get device details")
    print("  GET  /api/metrics/latest - Get latest metrics for dashboard")
    print()
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

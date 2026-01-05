#!/usr/bin/env python3
"""
Independent System Monitor Client
==================================
Collects system metrics via SNMP or direct system calls and sends to backend.
Run this independently on any device you want to monitor.

Usage:
    pip install psutil pysnmp requests
    python monitor_client.py --backend http://localhost:5000 --device-id MY-LAPTOP

For SNMP monitoring of remote devices:
    python monitor_client.py --snmp --host 192.168.1.100 --community public
"""

import argparse
import json
import time
import socket
import platform
import threading
from datetime import datetime
from typing import Dict, Any, Optional

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    print("Warning: psutil not installed. Install with: pip install psutil")

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False
    print("Warning: requests not installed. Install with: pip install requests")

try:
    # Import all SNMP components with explicit names
    from pysnmp.hlapi import (  # type: ignore
        getCmd, nextCmd, SnmpEngine, CommunityData, UdpTransportTarget,
        ContextData, ObjectType, ObjectIdentity
    )
    SNMP_AVAILABLE = True
except ImportError:
    SNMP_AVAILABLE = False
    print("Info: pysnmp not installed. SNMP monitoring disabled. Install with: pip install pysnmp")
    # Define dummy attributes to prevent Pylance undefined variable errors
    getCmd = None  # type: ignore
    nextCmd = None  # type: ignore
    SnmpEngine = None  # type: ignore
    CommunityData = None  # type: ignore
    UdpTransportTarget = None  # type: ignore
    ContextData = None  # type: ignore
    ObjectType = None  # type: ignore
    ObjectIdentity = None  # type: ignore


class SystemMetricsCollector:
    """Collects system metrics from local machine using psutil."""
    
    def __init__(self, device_id: str = None):
        self.device_id = device_id or socket.gethostname()
        self.device_type = "local"
        
    def collect(self) -> Dict[str, Any]:
        """Collect all system metrics."""
        if not PSUTIL_AVAILABLE:
            return self._get_fallback_metrics()
        
        try:
            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            net_io = psutil.net_io_counters()
            
            # Get CPU temperature if available
            cpu_temp = None
            try:
                temps = psutil.sensors_temperatures()
                if temps:
                    for name, entries in temps.items():
                        if entries:
                            cpu_temp = entries[0].current
                            break
            except:
                pass
            
            # Get network status
            net_connections = len(psutil.net_connections())
            
            return {
                "device_id": self.device_id,
                "device_type": self.device_type,
                "hostname": socket.gethostname(),
                "platform": platform.system(),
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "metrics": {
                    "cpu": {
                        "usage_percent": cpu_percent,
                        "cores": psutil.cpu_count(),
                        "frequency_mhz": psutil.cpu_freq().current if psutil.cpu_freq() else None,
                        "status": "healthy" if cpu_percent < 80 else "warning" if cpu_percent < 95 else "critical"
                    },
                    "memory": {
                        "total_gb": round(memory.total / (1024**3), 2),
                        "used_gb": round(memory.used / (1024**3), 2),
                        "available_gb": round(memory.available / (1024**3), 2),
                        "usage_percent": memory.percent,
                        "status": "healthy" if memory.percent < 80 else "warning" if memory.percent < 95 else "critical"
                    },
                    "disk": {
                        "total_gb": round(disk.total / (1024**3), 2),
                        "used_gb": round(disk.used / (1024**3), 2),
                        "free_gb": round(disk.free / (1024**3), 2),
                        "usage_percent": disk.percent,
                        "status": "healthy" if disk.percent < 80 else "warning" if disk.percent < 95 else "critical"
                    },
                    "network": {
                        "bytes_sent": net_io.bytes_sent,
                        "bytes_recv": net_io.bytes_recv,
                        "packets_sent": net_io.packets_sent,
                        "packets_recv": net_io.packets_recv,
                        "connections": net_connections,
                        "status": "healthy"
                    },
                    "temperature": {
                        "cpu_celsius": cpu_temp,
                        "status": "healthy" if not cpu_temp or cpu_temp < 70 else "warning" if cpu_temp < 85 else "critical"
                    },
                    "system": {
                        "boot_time": datetime.fromtimestamp(psutil.boot_time()).isoformat(),
                        "uptime_hours": round((time.time() - psutil.boot_time()) / 3600, 2),
                        "status": "healthy"
                    }
                },
                "overall_status": self._calculate_overall_status(cpu_percent, memory.percent, disk.percent)
            }
        except Exception as e:
            print(f"Error collecting metrics: {e}")
            return self._get_fallback_metrics()
    
    def _calculate_overall_status(self, cpu: float, memory: float, disk: float) -> str:
        """Calculate overall system health status."""
        if cpu > 95 or memory > 95 or disk > 95:
            return "critical"
        if cpu > 80 or memory > 80 or disk > 80:
            return "warning"
        return "healthy"
    
    def _get_fallback_metrics(self) -> Dict[str, Any]:
        """Return fallback metrics when psutil is not available."""
        return {
            "device_id": self.device_id,
            "device_type": self.device_type,
            "hostname": socket.gethostname(),
            "platform": platform.system(),
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "metrics": {
                "cpu": {"status": "unknown", "usage_percent": None},
                "memory": {"status": "unknown", "usage_percent": None},
                "disk": {"status": "unknown", "usage_percent": None},
                "network": {"status": "unknown"},
                "temperature": {"status": "unknown"},
                "system": {"status": "unknown"}
            },
            "overall_status": "unknown",
            "error": "psutil not available"
        }


class SNMPMetricsCollector:
    """Collects system metrics from remote devices via SNMP."""
    
    # Common SNMP OIDs
    OIDS = {
        "system_descr": "1.3.6.1.2.1.1.1.0",
        "system_uptime": "1.3.6.1.2.1.1.3.0",
        "system_name": "1.3.6.1.2.1.1.5.0",
        # Host Resources MIB
        "hr_processor_load": "1.3.6.1.2.1.25.3.3.1.2",  # CPU Load
        "hr_storage_used": "1.3.6.1.2.1.25.2.3.1.6",    # Storage Used
        "hr_storage_size": "1.3.6.1.2.1.25.2.3.1.5",    # Storage Size
        # IF-MIB for network
        "if_in_octets": "1.3.6.1.2.1.2.2.1.10",
        "if_out_octets": "1.3.6.1.2.1.2.2.1.16",
    }
    
    def __init__(self, host: str, community: str = "public", port: int = 161, device_id: str = None):
        self.host = host
        self.community = community
        self.port = port
        self.device_id = device_id or f"snmp-{host}"
        self.device_type = "snmp"
        
        if not SNMP_AVAILABLE:
            raise ImportError("pysnmp is required for SNMP monitoring. Install with: pip install pysnmp")
    
    def _snmp_get(self, oid: str) -> Optional[str]:
        """Perform SNMP GET request."""
        try:
            iterator = getCmd(
                SnmpEngine(),
                CommunityData(self.community),
                UdpTransportTarget((self.host, self.port), timeout=2, retries=1),
                ContextData(),
                ObjectType(ObjectIdentity(oid))
            )
            
            error_indication, error_status, error_index, var_binds = next(iterator)
            
            if error_indication or error_status:
                return None
            
            for var_bind in var_binds:
                return str(var_bind[1])
                
        except Exception as e:
            print(f"SNMP error for {oid}: {e}")
            return None
        
        return None
    
    def _snmp_walk(self, oid: str) -> list:
        """Perform SNMP WALK request."""
        results = []
        try:
            for (error_indication, error_status, error_index, var_binds) in nextCmd(
                SnmpEngine(),
                CommunityData(self.community),
                UdpTransportTarget((self.host, self.port), timeout=2, retries=1),
                ContextData(),
                ObjectType(ObjectIdentity(oid)),
                lexicographicMode=False
            ):
                if error_indication or error_status:
                    break
                for var_bind in var_binds:
                    results.append(str(var_bind[1]))
        except Exception as e:
            print(f"SNMP walk error for {oid}: {e}")
        
        return results
    
    def collect(self) -> Dict[str, Any]:
        """Collect metrics via SNMP."""
        system_descr = self._snmp_get(self.OIDS["system_descr"]) or "Unknown"
        system_name = self._snmp_get(self.OIDS["system_name"]) or self.host
        uptime_ticks = self._snmp_get(self.OIDS["system_uptime"])
        
        # Get CPU loads
        cpu_loads = self._snmp_walk(self.OIDS["hr_processor_load"])
        avg_cpu = sum(int(x) for x in cpu_loads) / len(cpu_loads) if cpu_loads else None
        
        # Calculate uptime
        uptime_hours = None
        if uptime_ticks:
            try:
                uptime_hours = round(int(uptime_ticks) / 100 / 3600, 2)
            except:
                pass
        
        return {
            "device_id": self.device_id,
            "device_type": self.device_type,
            "hostname": system_name,
            "host_address": self.host,
            "platform": system_descr[:50] if system_descr else "Unknown",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "metrics": {
                "cpu": {
                    "usage_percent": avg_cpu,
                    "status": "healthy" if not avg_cpu or avg_cpu < 80 else "warning" if avg_cpu < 95 else "critical"
                },
                "memory": {
                    "status": "healthy"  # Would need specific OIDs for memory
                },
                "disk": {
                    "status": "healthy"  # Would need specific OIDs for disk
                },
                "network": {
                    "status": "healthy"
                },
                "temperature": {
                    "status": "unknown"  # Device specific
                },
                "system": {
                    "uptime_hours": uptime_hours,
                    "status": "healthy" if uptime_ticks else "unknown"
                }
            },
            "overall_status": "healthy" if avg_cpu is None or avg_cpu < 80 else "warning"
        }


class MonitorClient:
    """Main monitor client that sends metrics to backend."""
    
    def __init__(self, backend_url: str, collector, interval: int = 5, api_key: str = None):
        self.backend_url = backend_url.rstrip('/')
        self.collector = collector
        self.interval = interval
        self.api_key = api_key
        self.running = False
        self._thread = None
        
    def _send_metrics(self, metrics: Dict[str, Any]) -> bool:
        """Send metrics to backend."""
        if not REQUESTS_AVAILABLE:
            print("requests library not available")
            return False
            
        try:
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["X-API-Key"] = self.api_key
            
            # Ensure backend_url is just the base (no trailing endpoint)    
            base_url = self.backend_url.rstrip('/')
            # Remove any trailing /api/metrics/ingest if present
            if base_url.endswith('/api/metrics/ingest'):
                base_url = base_url.replace('/api/metrics/ingest', '')
                
            response = requests.post(
                f"{base_url}/api/metrics/ingest",
                json=metrics,
                headers=headers,
                timeout=10
            )
            
            if response.status_code == 200:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Metrics sent successfully")
                return True
            else:
                print(f"Failed to send metrics: {response.status_code} - {response.text}")
                return False
                
        except requests.exceptions.ConnectionError:
            print(f"Cannot connect to backend at {self.backend_url}")
            return False
        except Exception as e:
            print(f"Error sending metrics: {e}")
            return False
    
    def _monitor_loop(self):
        """Main monitoring loop."""
        while self.running:
            try:
                metrics = self.collector.collect()
                self._send_metrics(metrics)
            except Exception as e:
                print(f"Error in monitor loop: {e}")
            
            time.sleep(self.interval)
    
    def start(self):
        """Start the monitoring client."""
        self.running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()
        print(f"Monitor started for device: {self.collector.device_id}")
        print(f"Sending metrics to: {self.backend_url}")
        print(f"Interval: {self.interval} seconds")
        print("Press Ctrl+C to stop...")
        
    def stop(self):
        """Stop the monitoring client."""
        self.running = False
        if self._thread:
            self._thread.join(timeout=5)
        print("Monitor stopped")
    
    def run_once(self):
        """Collect and send metrics once."""
        metrics = self.collector.collect()
        print(json.dumps(metrics, indent=2))
        return self._send_metrics(metrics)


def main():
    parser = argparse.ArgumentParser(description="System Monitor Client")
    parser.add_argument("--backend", default="http://localhost:5000", help="Backend URL")
    parser.add_argument("--device-id", help="Device identifier")
    parser.add_argument("--interval", type=int, default=30, help="Polling interval in seconds")
    parser.add_argument("--api-key", help="API key for authentication")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    
    # SNMP options
    parser.add_argument("--snmp", action="store_true", help="Use SNMP for remote device")
    parser.add_argument("--host", help="SNMP target host")
    parser.add_argument("--community", default="public", help="SNMP community string")
    parser.add_argument("--port", type=int, default=161, help="SNMP port")
    
    args = parser.parse_args()
    
    # Create appropriate collector
    if args.snmp:
        if not args.host:
            print("Error: --host is required for SNMP mode")
            return
        collector = SNMPMetricsCollector(
            host=args.host,
            community=args.community,
            port=args.port,
            device_id=args.device_id
        )
    else:
        collector = SystemMetricsCollector(device_id=args.device_id)
    
    # Create and run client
    client = MonitorClient(
        backend_url=args.backend,
        collector=collector,
        interval=args.interval,
        api_key=args.api_key
    )
    
    if args.once:
        client.run_once()
    else:
        try:
            client.start()
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            client.stop()


if __name__ == "__main__":
    main()

"""
system_info.py

Tool: system_info
Monitorización del sistema: CPU, RAM, disco, batería, red, procesos.
Requiere: psutil
"""

from __future__ import annotations

import platform
from datetime import datetime, timedelta
from typing import Any, Dict


def _try_psutil() -> Any:
    try:
        import psutil
        return psutil
    except ImportError:
        return None


def run_system_info(args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Args:
      - action: cpu | ram | disk | battery | network | processes | all | uptime (obligatorio)
      - top_n: número de procesos a mostrar (para processes, default 10)

    Returns: dict con métricas del sistema.
    """
    action = str(args.get("action", "all")).lower().strip()
    top_n = int(args.get("top_n", 10))

    psutil = _try_psutil()
    if psutil is None:
        return {
            "ok": False,
            "error": "psutil no instalado. Ejecuta: pip install psutil",
        }

    result: Dict[str, Any] = {"ok": True, "action": action}

    try:
        if action in ("cpu", "all"):
            result["cpu"] = {
                "percent": psutil.cpu_percent(interval=0.5),
                "cores_physical": psutil.cpu_count(logical=False),
                "cores_logical": psutil.cpu_count(logical=True),
                "freq_mhz": round(psutil.cpu_freq().current, 0) if psutil.cpu_freq() else None,
            }

        if action in ("ram", "all"):
            vm = psutil.virtual_memory()
            result["ram"] = {
                "total_gb": round(vm.total / 1e9, 2),
                "used_gb": round(vm.used / 1e9, 2),
                "available_gb": round(vm.available / 1e9, 2),
                "percent": vm.percent,
            }

        if action in ("disk", "all"):
            disk = psutil.disk_usage("/")
            result["disk"] = {
                "total_gb": round(disk.total / 1e9, 1),
                "used_gb": round(disk.used / 1e9, 1),
                "free_gb": round(disk.free / 1e9, 1),
                "percent": disk.percent,
            }

        if action in ("battery", "all"):
            bat = psutil.sensors_battery()
            if bat:
                result["battery"] = {
                    "percent": round(bat.percent, 1),
                    "plugged": bat.power_plugged,
                    "time_left_min": round(bat.secsleft / 60, 0) if bat.secsleft > 0 else None,
                }
            else:
                result["battery"] = {"available": False}

        if action in ("network", "all"):
            net = psutil.net_io_counters()
            result["network"] = {
                "bytes_sent_mb": round(net.bytes_sent / 1e6, 2),
                "bytes_recv_mb": round(net.bytes_recv / 1e6, 2),
                "packets_sent": net.packets_sent,
                "packets_recv": net.packets_recv,
            }

        if action in ("uptime", "all"):
            boot_time = psutil.boot_time()
            uptime_sec = (datetime.now().timestamp() - boot_time)
            uptime = timedelta(seconds=int(uptime_sec))
            hours, remainder = divmod(uptime.seconds, 3600)
            minutes = remainder // 60
            days = uptime.days
            result["uptime"] = {
                "days": days,
                "hours": hours,
                "minutes": minutes,
                "human": f"{days}d {hours}h {minutes}m" if days > 0 else f"{hours}h {minutes}m",
                "boot_time": datetime.fromtimestamp(boot_time).strftime("%Y-%m-%d %H:%M"),
            }

        if action == "processes":
            procs = []
            for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
                try:
                    info = p.info
                    procs.append({
                        "pid": info["pid"],
                        "name": info["name"],
                        "cpu_pct": round(info["cpu_percent"] or 0, 1),
                        "mem_pct": round(info["memory_percent"] or 0, 2),
                    })
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

            procs.sort(key=lambda x: x["cpu_pct"], reverse=True)
            result["processes"] = procs[:top_n]
            result["total_processes"] = len(procs)

        # Añadir plataforma siempre
        result["platform"] = {
            "system": platform.system(),
            "node": platform.node(),
            "version": platform.mac_ver()[0] if platform.system() == "Darwin" else platform.version(),
        }

    except Exception as e:
        result["ok"] = False
        result["error"] = str(e)

    return result

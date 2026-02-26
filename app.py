# Based on TrueNAS API v25.10.2 specifications
from __future__ import annotations

import eventlet
eventlet.monkey_patch()

import os
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import urlparse
import time
from functools import lru_cache
import concurrent.futures
import base64
import io
import shlex

import urllib3
import requests
import threading
import paramiko
from flask_socketio import SocketIO, emit
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'secret!')
socketio = SocketIO(app, cors_allowed_origins="*")

log_dir = Path(__file__).parent / "logs"
log_dir.mkdir(exist_ok=True)
log_file = log_dir / "app.log"
file_handler = RotatingFileHandler(log_file, maxBytes=1_000_000, backupCount=3)
file_handler.setLevel("INFO")
app.logger.addHandler(file_handler)

TRUENAS_HOST = os.getenv("TRUENAS_HOST", "").strip()
TRUENAS_API_KEY = os.getenv("TRUENAS_API_KEY", "").strip()
TRUENAS_SCHEME = os.getenv("TRUENAS_SCHEME", "https").strip() or "https"
TRUENAS_PORT = os.getenv("TRUENAS_PORT", "").strip()
TRUENAS_VERIFY_SSL = os.getenv("TRUENAS_VERIFY_SSL", "true").strip().lower()
TRUENAS_DISPLAY_IP = os.getenv("TRUENAS_DISPLAY_IP", "").strip() or TRUENAS_HOST
NETDATA_HOST = os.getenv("NETDATA_HOST", "").strip()
NETDATA_PORT = os.getenv("NETDATA_PORT", "19999").strip() or "19999"
NETDATA_URL = os.getenv("NETDATA_URL", "").strip()
NETDATA_SCHEME = os.getenv("NETDATA_SCHEME", "http").strip() or "http"
NETDATA_VERIFY_SSL = os.getenv("NETDATA_VERIFY_SSL", "true").strip().lower()
NETDATA_BASE_PATH = os.getenv("NETDATA_BASE_PATH", "").strip()
NETDATA_BEARER_TOKEN = os.getenv("NETDATA_BEARER_TOKEN", "").strip()
NETDATA_DATA_ENDPOINT = os.getenv("NETDATA_DATA_ENDPOINT", "/api/v1/data").strip()
NETDATA_CHART_CPU = os.getenv("NETDATA_CHART_CPU", "").strip()
NETDATA_CHART_RAM = os.getenv("NETDATA_CHART_RAM", "").strip()
NETDATA_CHART_DISK1 = os.getenv("NETDATA_CHART_DISK1", "").strip()
NETDATA_CHART_DISK2 = os.getenv("NETDATA_CHART_DISK2", "").strip()
NETDATA_CHART_NET1 = os.getenv("NETDATA_CHART_NET1", "").strip()
NETDATA_CHART_NET2 = os.getenv("NETDATA_CHART_NET2", "").strip()
NETDATA_LABEL_DISK1 = os.getenv("NETDATA_LABEL_DISK1", "Disk 1").strip() or "Disk 1"
NETDATA_LABEL_DISK2 = os.getenv("NETDATA_LABEL_DISK2", "Disk 2").strip() or "Disk 2"
NETDATA_LABEL_NET1 = os.getenv("NETDATA_LABEL_NET1", "NIC 1").strip() or "NIC 1"
NETDATA_LABEL_NET2 = os.getenv("NETDATA_LABEL_NET2", "NIC 2").strip() or "NIC 2"
NETDATA_CHART_CPU_TEMP = os.getenv("NETDATA_CHART_CPU_TEMP", "sensors.temperature_coretemp-isa-0000_temp1_Package_id_0_input").strip()

SPEC_CPU_MODEL = os.getenv("SPEC_CPU_MODEL", "Intel Core i5-12400").strip()
SPEC_RAM_TEXT = os.getenv("SPEC_RAM_TEXT", "64GB DDR4 ECC").strip()
SPEC_POOL1_TEXT = os.getenv("SPEC_POOL1_TEXT", "4x 8TB HDD").strip()
SPEC_POOL2_TEXT = os.getenv("SPEC_POOL2_TEXT", "2x 1TB NVMe").strip()
SPEC_GPU_TEXT = os.getenv("SPEC_GPU_TEXT", "NVIDIA Tesla P4 8GB").strip()

TRUENAS_INTERFACE_NET1 = os.getenv("TRUENAS_INTERFACE_NET1", "eno1").strip()
TRUENAS_INTERFACE_NET2 = os.getenv("TRUENAS_INTERFACE_NET2", "enp3s0").strip()

APPS_CONFIG = [
    {
        "category": "Media",
        "icon": "fa-play",
        "color": "text-pink-400 group-hover:text-pink-300",
        "apps": [
            {"name": "Jellyfin", "port": 8096, "icon": "jellyfin.png"},
            {"name": "Jellyseerr", "port": 5055, "icon": "jellyseerr.png"},
            {"name": "Navidrome", "port": 4533, "icon": "navidrome.png"},
            {"name": "MusicTag", "port": 8002, "icon": "musictag.png"},
            {"name": "Immich", "port": 2283, "icon": "immich.png"},
        ]
    },
    {
        "category": "Arr Stack",
        "icon": "fa-layer-group",
        "color": "text-cyan-400 group-hover:text-cyan-300",
        "apps": [
            {"name": "Sonarr", "port": 8989, "icon": "sonarr.png"},
            {"name": "Radarr", "port": 7878, "icon": "radarr.png"},
            {"name": "Bazarr", "port": 6767, "icon": "bazarr.png"},
            {"name": "Prowlarr", "port": 9696, "icon": "prowlarr.png"},
            {"name": "Tidarr", "port": 8484, "icon": "tidarr.png"},
        ]
    },
    {
        "category": "Downloads",
        "icon": "fa-download",
        "color": "text-emerald-400 group-hover:text-emerald-300",
        "apps": [
            {"name": "Real Debrid", "port": 6500, "icon": "realtime-debrid.png"},
            {"name": "Slskd", "port": 5030, "icon": "slskd.png"},
        ]
    },
    {
        "category": "System",
        "icon": "fa-toolbox",
        "color": "text-amber-400 group-hover:text-amber-300",
        "apps": [
            {"name": "AdGuard", "port": 30004, "icon": "adguard.png"},
            {"name": "Netdata", "port": 20489, "icon": "netdata.png"},
            {"name": "Syncthing", "port": 20910, "icon": "syncthing.png"},
            {"name": "Obsidian", "port": 9080, "icon": "obsidian.png"},
            {"name": "FileBrowser", "port": 30051, "icon": "filebrowser.png"},
            {"name": "Uptime Kuma", "port": 31050, "icon": "uptime-kuma.png"},
        ]
    },
]

CACHE_DURATION_DATASETS = 60
CACHE_DURATION_DISKS = 300

if TRUENAS_VERIFY_SSL in {"false", "0", "no"} or NETDATA_VERIFY_SSL in {"false", "0", "no"}:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def _build_base_url() -> str:
    if not TRUENAS_HOST:
        raise ValueError("TRUENAS_HOST not set")
    host = TRUENAS_HOST
    if TRUENAS_PORT:
        host = f"{host}:{TRUENAS_PORT}"
    return f"{TRUENAS_SCHEME}://{host}"


def _build_headers() -> dict[str, str]:
    if not TRUENAS_API_KEY:
        return {}
    return {"Authorization": f"Bearer {TRUENAS_API_KEY}"}


def _fetch_truenas(path: str, params: dict | None = None) -> dict | list:
    url = f"{_build_base_url()}{path}"
    verify_ssl = TRUENAS_VERIFY_SSL not in {"false", "0", "no"}
    try:
        response = requests.get(
            url,
            headers=_build_headers(),
            params=params,
            timeout=5, # Increased timeout for responsiveness
            verify=verify_ssl,
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        app.logger.warning(f"TrueNAS Fetch Error [{path}]: {e}")
        raise

def _post_truenas(path: str, json_data: dict | None = None) -> dict | list:
    url = f"{_build_base_url()}{path}"
    verify_ssl = TRUENAS_VERIFY_SSL not in {"false", "0", "no"}
    try:
        response = requests.post(
            url,
            headers=_build_headers(),
            json=json_data,
            timeout=5, # Increased timeout
            verify=verify_ssl,
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        app.logger.warning(f"TrueNAS Post Error [{path}]: {e}")
        raise


_truenas_cache_store = {}

def _fetch_truenas_cached(path: str, params: dict | None = None, cache_duration: int = 60) -> dict | list:
    key_params = frozenset(params.items()) if params else None
    key = (path, key_params)
    now = time.time()
    
    if key in _truenas_cache_store:
        timestamp, data = _truenas_cache_store[key]
        if now - timestamp < cache_duration:
            return data

    data = _fetch_truenas(path, params)
    _truenas_cache_store[key] = (now, data)
    
    if len(_truenas_cache_store) > 100:
        _truenas_cache_store.clear()
        _truenas_cache_store[key] = (now, data)
        
    return data


def _build_netdata_base_url() -> str:
    if NETDATA_URL:
        parsed = urlparse(NETDATA_URL)
        if not parsed.scheme:
            parsed = urlparse(f"http://{NETDATA_URL}")
        base_url = f"{parsed.scheme}://{parsed.netloc}"
    elif NETDATA_HOST:
        base_url = f"{NETDATA_SCHEME}://{NETDATA_HOST}:{NETDATA_PORT}"
    else:
        return ""
    if NETDATA_BASE_PATH:
        path = NETDATA_BASE_PATH if NETDATA_BASE_PATH.startswith("/") else f"/{NETDATA_BASE_PATH}"
        return f"{base_url}{path.rstrip('/')}"
    return base_url


def _fetch_netdata(path: str, params: dict | None = None) -> dict | None:
    base_url = _build_netdata_base_url()
    if not base_url:
        return None
    verify_ssl = NETDATA_VERIFY_SSL not in {"false", "0", "no"}
    headers = {}
    if NETDATA_BEARER_TOKEN:
        headers["Authorization"] = f"Bearer {NETDATA_BEARER_TOKEN}"
    
    try:
        response = requests.get(
            f"{base_url}{path}",
            params=params,
            timeout=2, # Increased timeout for Netdata
            verify=verify_ssl,
            headers=headers,
        )
        if not response.ok:
            # Don't raise, just log and return None to allow partial dashboard loading
            app.logger.debug(f"Netdata request failed: {response.status_code}")
            return None
        return response.json()
    except requests.exceptions.RequestException as e:
        app.logger.debug(f"Netdata Connection Error: {e}")
        return None


def _format_request_error(message: str, exc: requests.RequestException) -> dict:
    details = str(exc)
    status_code = None
    response_text = None
    if getattr(exc, "response", None) is not None:
        status_code = exc.response.status_code
        response_text = (exc.response.text or "").strip()[:500]
    return {
        "error": message,
        "details": details,
        "status_code": status_code,
        "response": response_text,
        "netdata_base_url": _build_netdata_base_url(),
        "netdata_data_endpoint": NETDATA_DATA_ENDPOINT,
    }


def _netdata_latest(chart: str) -> dict[str, float] | None:
    if not chart:
        return None
    try:
        payload = _fetch_netdata(
            NETDATA_DATA_ENDPOINT,
            params={
                "chart": chart,
                "after": "-1", 
                "format": "json",
            },
        )
    except Exception:
        return None

    if not payload:
        return None
    labels = payload.get("labels") or []
    data = payload.get("data") or []
    if not labels or not data:
        return None
    
    last_row = data[0]
    values: dict[str, float] = {}
    for label, value in zip(labels, last_row):
        if label == "time":
            continue
        try:
            values[label] = float(value)
        except (TypeError, ValueError):
            continue
    return values


def _calc_cpu_usage(latest: dict[str, float] | None) -> float | None:
    if not latest:
        return None
    if "idle" in latest:
        return max(0.0, 100.0 - latest["idle"])
    if "user" in latest and "system" in latest:
        return max(0.0, latest["user"] + latest["system"])
    return None


def _get_gpu_stats() -> dict | None:
    try:
        import subprocess
        # Get utilization.gpu, temperature.gpu, memory.used, memory.total
        cmd = ['nvidia-smi', '--query-gpu=utilization.gpu,temperature.gpu,memory.used,memory.total', '--format=csv,noheader,nounits']
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=1)
        
        if result.returncode != 0:
            return None
            
        line = result.stdout.strip()
        if not line:
            return None
            
        parts = [x.strip() for x in line.split(',')]
        if len(parts) < 4:
            return None
            
        return {
            "utilization": float(parts[0]),
            "temperature": float(parts[1]),
            "memory_used": float(parts[2]),
            "memory_total": float(parts[3])
        }
    except Exception:
        return None


def _calc_memory(latest: dict[str, float] | None) -> dict[str, float] | None:
    if not latest:
        return None
    used = latest.get("used") or latest.get("used_ram")
    free = latest.get("free")
    cached = latest.get("cached", 0.0)
    buffers = latest.get("buffers", 0.0)
    
    if used is None:
        return None
        
    total = 0.0
    for value in (used, free, cached, buffers):
        if isinstance(value, (int, float)):
            total += float(value)
            
    if total <= 0:
        total = used

    if free is not None:
        calculated_used = total - float(free)
    else:
        calculated_used = used
    
    app_used = float(used) if used is not None else 0.0
    cache_used = float(cached) + float(buffers)
    
    app_percent = (app_used / total * 100.0) if total else 0.0
    cache_percent = (cache_used / total * 100.0) if total else 0.0
    
    used_percent = (calculated_used / total * 100.0) if total else None
    
    return {
        "used": calculated_used, 
        "total": total, 
        "used_percent": used_percent,
        "apps": app_used,
        "cache": cache_used,
        "apps_percent": app_percent,
        "cache_percent": cache_percent
    }


def _calc_cpu_temp(latest: dict[str, float] | None) -> float | None:
    if not latest:
        return None
    return latest.get("input")


def _calc_disk_usage(
    latest: dict[str, float] | None,
    label: str,
) -> dict[str, float | str] | None:
    if not latest:
        return None
    used = latest.get("used")
    avail = latest.get("avail") or latest.get("free")
    if used is None or avail is None:
        return None
    total = used + avail
    used_percent = (used / total * 100.0) if total else None
    return {"label": label, "used": used, "total": total, "used_percent": used_percent}


def _calc_net_io(
    latest: dict[str, float] | None,
    label: str,
) -> dict[str, float | str] | None:
    if not latest:
        return None
    rx = latest.get("received") or latest.get("rx")
    tx = latest.get("sent") or latest.get("tx")
    
    if rx is not None:
        rx = abs(rx) * 1000 / 8 
    
    if tx is not None:
        tx = abs(tx) * 1000 / 8

    if rx is None or tx is None:
        return None
        
    return {"label": label, "rx": rx, "tx": tx}


def _get_truenas_dataset_usage(mountpoint: str, label: str) -> dict | None:
    try:
        datasets = _fetch_truenas_cached("/api/v2.0/pool/dataset", params={"mountpoint": mountpoint}, cache_duration=CACHE_DURATION_DATASETS)
    except Exception as e:
        app.logger.error(f"Failed to fetch dataset for {mountpoint}: {e}")
        return None

    if not datasets or not isinstance(datasets, list):
        return None

    ds = next((d for d in datasets if d.get("mountpoint") == mountpoint), None)
    if not ds:
        return None

    def _extract_val(field):
        if isinstance(field, dict):
            return field.get("parsed") or field.get("value")
        return field

    used = _extract_val(ds.get("used"))
    avail = _extract_val(ds.get("available"))

    if used is None or avail is None:
        return None

    try:
        used_bytes = float(used)
        avail_bytes = float(avail)
        total_bytes = used_bytes + avail_bytes
        used_percent = (used_bytes / total_bytes * 100.0) if total_bytes > 0 else 0.0
        
        gib_divisor = 1024.0 ** 3
        
        return {
            "label": label,
            "used": used_bytes / gib_divisor,
            "total": total_bytes / gib_divisor,
            "used_percent": used_percent
        }
    except (ValueError, TypeError):
        return None


def _get_disk_info() -> list[dict] | None:
    try:
        try:
            disks = _fetch_truenas_cached("/api/v2.0/disk", params={"limit": 0}, cache_duration=CACHE_DURATION_DISKS)
        except requests.exceptions.HTTPError as e:
            app.logger.warning(f"Failed to fetch /disk: {e}")
            return None
        
        try:
            temps = _post_truenas("/api/v2.0/disk/temperatures")
        except Exception as e:
            app.logger.warning(f"Failed to fetch temps via /disk/temperatures (POST): {e}")
            temps = {}

    except Exception as e:
        app.logger.error(f"Failed to fetch disk info: {e}")
        return None

    if not isinstance(disks, list):
        return None
    
    result = []
    for disk in disks:
        name = disk.get("name")
        if not name:
            continue
            
        model = disk.get("model") or "Unknown Model"
        serial = disk.get("serial") or ""
        size_bytes = disk.get("size") or 0
        description = disk.get("description") or ""
        
        disk_type = "HDD"
        api_type = disk.get("type")
        if api_type == "SSD" or "ssd" in model.lower():
            disk_type = "SSD"
        elif "nvme" in name.lower() or "nvd" in name.lower() or "nvme" in model.lower():
            disk_type = "NVMe"
        
        temp = temps.get(name) if isinstance(temps, dict) else None
        
        result.append({
            "name": name,
            "model": model,
            "serial": serial,
            "size": size_bytes,
            "temp": temp,
            "type": disk_type,
            "description": description
        })

    # --- Fallback: for disks with no temperature (e.g. SATA-over-USB bridges),
    #     try smartctl with SAT passthrough via SSH. ---
    missing_temp = [d for d in result if d["temp"] is None]
    if missing_temp and (os.getenv("SSH_PRIVATE_KEY_B64") or os.getenv("SSH_PASSWORD")):
        import json as _json

        def _fetch_temp_sat(disk: dict) -> int | None:
            dev = f"/dev/{disk['name']}"
            for dtype in ("sat", "sat,auto"):
                try:
                    out, _ = _ssh_exec(f"sudo smartctl -d {dtype} --json -A {dev}", timeout=15)
                    if not out.strip():
                        continue
                    sj = _json.loads(out)
                    t = (sj.get("temperature") or {}).get("current")
                    if t is not None:
                        app.logger.info(f"Temp fallback via -d {dtype} for {dev}: {t}°C")
                        return t
                except Exception as e:
                    app.logger.debug(f"Temp fallback failed for {dev} (dtype={dtype}): {e}")
            return None

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
            futures = {ex.submit(_fetch_temp_sat, d): d for d in missing_temp}
            for fut, disk in futures.items():
                try:
                    t = fut.result(timeout=20)
                    if t is not None:
                        disk["temp"] = t
                except Exception:
                    pass

    return result


def _get_system_info_truenas() -> dict:
    # Cache for a long time (e.g. 1 hour) as hardware doesn't change often
    try:
        info = _fetch_truenas_cached("/api/v2.0/system/info", cache_duration=3600)
    except Exception as e:
        app.logger.warning(f"Failed to fetch system info: {e}")
        return {}
    
    # "model" in system/info is usually the chassis/mobo model (e.g. "Generic")
    # "cpu_model" is the actual processor name
    cpu_model = info.get("cpu_model", "")
    if not cpu_model:
        # Fallback if cpu_model is missing
        cpu_model = info.get("model", "")

    physmem = info.get("physmem", 0)
    
    ram_str = ""
    if physmem:
        gib = physmem / (1024 ** 3)
        # If very close to integer, show integer
        if abs(gib - round(gib)) < 0.1:
            ram_str = f"{int(round(gib))}GB"
        else:
            ram_str = f"{gib:.1f}GB"
            
    # Clean up CPU text
    # Example: Intel(R) Core(TM) i5-12400 CPU @ 2.50GHz -> Intel Core i5-12400
    if cpu_model:
        cpu_model = cpu_model.replace("(R)", "").replace("(TM)", "").replace("CPU", "").split("@")[0].strip()
        # Remove extra spaces
        cpu_model = " ".join(cpu_model.split())
        
    return {
        "cpu_model": cpu_model,
        "ram_text": ram_str
    }


@app.route("/")
def index() -> str:
    # Fixed CPU and RAM as requested
    final_cpu = "Intel Xeon E3-1230v3 @3.30GHz"
    final_ram = "32GiB DDR3"

    return render_template(
        "index.html",
        netdata_host=NETDATA_HOST,
        netdata_port=NETDATA_PORT,
        netdata_url=NETDATA_URL,
        spec_cpu=final_cpu,
        spec_ram=final_ram,
        spec_pool1=SPEC_POOL1_TEXT,
        spec_pool2=SPEC_POOL2_TEXT,
        spec_gpu=SPEC_GPU_TEXT,
        truenas_ip=TRUENAS_DISPLAY_IP,
        truenas_ssh_user=os.getenv('SSH_USER', 'root'),
        apps=APPS_CONFIG,
    )


@app.route("/api/metrics")
def api_metrics():
    try:
        # Defaults
        gpu_stats = None
        cpu_usage = 0.0
        memory = None
        cpu_temp = None
        disks = []
        nets = []
        
        # Use a timeout for futures to prevent blocking indefinitely
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            f_cpu = executor.submit(_netdata_latest, NETDATA_CHART_CPU)
            f_ram = executor.submit(_netdata_latest, NETDATA_CHART_RAM)
            f_temp = executor.submit(_netdata_latest, NETDATA_CHART_CPU_TEMP)
            
            f_n1_chart = executor.submit(_netdata_latest, NETDATA_CHART_NET1) if NETDATA_CHART_NET1 else None
            f_n1_iface = executor.submit(_netdata_latest, f"net.{TRUENAS_INTERFACE_NET1}") if TRUENAS_INTERFACE_NET1 else None
            
            f_n2_chart = executor.submit(_netdata_latest, NETDATA_CHART_NET2) if NETDATA_CHART_NET2 else None
            f_n2_iface = executor.submit(_netdata_latest, f"net.{TRUENAS_INTERFACE_NET2}") if TRUENAS_INTERFACE_NET2 else None

            f_store_1 = executor.submit(_get_truenas_dataset_usage, "/mnt/storage", "storage (/mnt/storage)")
            f_store_2 = executor.submit(_get_truenas_dataset_usage, "/mnt/Apps", "Apps (/mnt/Apps)")

            # Safe result retrieval with default None
            def get_res(f):
                try:
                    return f.result(timeout=6) if f else None
                except Exception as e:
                    app.logger.warning(f"Future timed out or failed: {e}")
                    return None

            cpu_latest = get_res(f_cpu)
            ram_latest = get_res(f_ram)
            temp_latest = get_res(f_temp)
            
            net1_chart_res = get_res(f_n1_chart)
            net1_iface_res = get_res(f_n1_iface)
            
            net2_chart_res = get_res(f_n2_chart)
            net2_iface_res = get_res(f_n2_iface)
            
            storage_disk = get_res(f_store_1)
            apps_disk = get_res(f_store_2)


        # Run GPU check in main thread or pool (fast enough)
        gpu_stats = _get_gpu_stats()

        cpu_temp = _calc_cpu_temp(temp_latest)

        net1_latest = None
        if net1_chart_res:
             net1_latest = _calc_net_io(net1_chart_res, NETDATA_LABEL_NET1)
        
        if not net1_latest and TRUENAS_INTERFACE_NET1:
             if net1_iface_res: 
                 net1_latest = _calc_net_io(net1_iface_res, NETDATA_LABEL_NET1)
             else:
                 net1_truenas = _get_truenas_net_stats(TRUENAS_INTERFACE_NET1)
                 if net1_truenas:
                    net1_latest = {"label": NETDATA_LABEL_NET1, "rx": net1_truenas["rx"], "tx": net1_truenas["tx"]}

        net2_latest = None
        if net2_chart_res:
             net2_latest = _calc_net_io(net2_chart_res, NETDATA_LABEL_NET2)

        if not net2_latest and TRUENAS_INTERFACE_NET2:
             if net2_iface_res:
                 net2_latest = _calc_net_io(net2_iface_res, NETDATA_LABEL_NET2)
             else:
                 net2_truenas = _get_truenas_net_stats(TRUENAS_INTERFACE_NET2)
                 if net2_truenas:
                    net2_latest = {"label": NETDATA_LABEL_NET2, "rx": net2_truenas["rx"], "tx": net2_truenas["tx"]}

        cpu_usage = _calc_cpu_usage(cpu_latest)
        memory = _calc_memory(ram_latest)

        disks = []
        if storage_disk: disks.append(storage_disk)
        if apps_disk: disks.append(apps_disk)

        nets = []
        if net1_latest:
            nets.append({"label": net1_latest["label"], "rx": net1_latest["rx"], "tx": net1_latest["tx"]})
        if net2_latest:
            nets.append({"label": net2_latest["label"], "rx": net2_latest["rx"], "tx": net2_latest["tx"]})

        return jsonify(
            {
                "gpu": gpu_stats,
                "system_ip": TRUENAS_DISPLAY_IP,
                "cpu_usage": cpu_usage,
                "cpu_temp": cpu_temp,
                "memory": memory,
                "disks": disks,
                "nets": nets,
            }
        )
    except Exception as exc:  # Catch all to ensure JSON return
        app.logger.error(f"Metrics Error: {exc}")
        # Return partial/empty structure to prevent frontend hanging
        return jsonify({
            "gpu": None,
            "system_ip": TRUENAS_DISPLAY_IP,
            "cpu_usage": 0,
            "cpu_temp": None,
            "memory": None,
            "disks": [],
            "nets": [],
            "error": str(exc)
        })



@app.route("/api/netdata/charts")
def api_netdata_charts():
    try:
        data = _fetch_netdata("/api/v1/charts")
        return jsonify(data or {})
    except requests.exceptions.RequestException as exc:
        return (
            jsonify(_format_request_error("Failed to reach Netdata", exc)),
            502,
        )
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": "Unexpected error", "details": str(exc)}), 500


@app.route("/api/netdata/contexts")
def api_netdata_contexts():
    try:
        data = _fetch_netdata("/api/v3/contexts")
        return jsonify(data or {})
    except requests.exceptions.RequestException as exc:
        return (
            jsonify(_format_request_error("Failed to reach Netdata", exc)),
            502,
        )
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": "Unexpected error", "details": str(exc)}), 500


@app.route("/api/stats")
def api_stats():
    try:
        if not TRUENAS_HOST or not TRUENAS_API_KEY:
            return jsonify({"error": "Missing TRUENAS_HOST or TRUENAS_API_KEY"}), 500

        with concurrent.futures.ThreadPoolExecutor() as executor:
            f_sys = executor.submit(_fetch_truenas, "/api/v2.0/system/info")
            f_pools = executor.submit(_fetch_truenas, "/api/v2.0/pool")
            f_disks = executor.submit(_get_disk_info)

            system_info = f_sys.result()
            pools = f_pools.result()
            disks_info = f_disks.result()

        uptime = system_info.get("uptime") or system_info.get("uptime_seconds")
        load = (
            system_info.get("loadavg")
            or system_info.get("load_avg")
            or system_info.get("load")
        )

        pool_items: list[dict[str, str]] = []
        if isinstance(pools, list):
            for pool in pools:
                name = pool.get("name") or pool.get("pool_name") or "Unknown"
                status = (
                    pool.get("status")
                    or pool.get("healthy")
                    or pool.get("status_description")
                    or "UNKNOWN"
                )
                if isinstance(status, bool):
                    status = "ONLINE" if status else "OFFLINE"
                pool_items.append({"name": str(name), "status": str(status).upper()})

        return jsonify({
            "uptime": uptime, 
            "load": load, 
            "pools": pool_items,
            "disks": disks_info
        })

    except ValueError as exc:
        return jsonify({"error": str(exc)}), 500
    except requests.exceptions.RequestException as exc:
        return (
            jsonify({"error": "Failed to reach TrueNAS", "details": str(exc)}),
            502,
        )
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": "Unexpected error", "details": str(exc)}), 500


_net_stats_cache = {}
CACHE_DURATION_NET = 3.0

def _get_truenas_net_stats(identifier: str) -> dict | None:
    now = time.time()
    if identifier in _net_stats_cache:
        ts, val = _net_stats_cache[identifier]
        if now - ts < CACHE_DURATION_NET:
            return val

    try:
        payload = {
            "graphs": [{"name": "interface", "identifier": identifier}]
        }
        resp = requests.post(
            f"{_build_base_url()}/api/v2.0/reporting/get_data",
            headers=_build_headers(),
            json=payload,
            verify=(TRUENAS_VERIFY_SSL not in {"false", "0", "no"}),
            timeout=5
        )
        if resp.status_code != 200:
            return None
        
        data = resp.json()
        if not data or not isinstance(data, list):
            return None
            
        chart = data[0]
        legend = chart.get("legend", [])
        series_list = chart.get("data", [])
        
        if not legend or not series_list:
            return None
            
        rx_idx = -1
        tx_idx = -1
        
        for i, leg in enumerate(legend):
            if "rx" in leg.lower() or "received" in leg.lower():
                rx_idx = i
            elif "tx" in leg.lower() or "sent" in leg.lower():
                tx_idx = i
        
        if rx_idx == -1 and tx_idx == -1 and len(legend) == 2:
            rx_idx = 0
            tx_idx = 1
            
        latest_rx = 0.0
        latest_tx = 0.0
        
        if rx_idx != -1 and len(series_list) > rx_idx:
            s = series_list[rx_idx]
            if s:
                for val in reversed(s):
                    if val is not None:
                        latest_rx = float(val)
                        break
                        
        if tx_idx != -1 and len(series_list) > tx_idx:
             s = series_list[tx_idx]
             if s:
                for val in reversed(s):
                    if val is not None:
                        latest_tx = float(val)
                        break
        
        result = {"rx": latest_rx, "tx": latest_tx}
        _net_stats_cache[identifier] = (now, result)
        return result

    except Exception as e:
        app.logger.warning(f"Failed to fetch net stats for {identifier}: {e}")
        return None


# --- SSH WebSocket Logic ---

ssh_client = None
ssh_channel = None

@socketio.on('connect', namespace='/ssh')
def connect_ssh():
    """Client connected via WebSocket"""
    print("Client connected via WebSocket")
    # 強制重置連線，確保每次進入 Terminal 都是新的 Session
    global ssh_client, ssh_channel
    if ssh_client:
        try:
            ssh_client.close()
        except:
            pass
    ssh_client = None
    ssh_channel = None
    init_ssh_connection()

@socketio.on('input', namespace='/ssh')
def handle_ssh_input(data):
    """Forward input to SSH"""
    global ssh_channel
    if ssh_channel and not ssh_channel.closed:
        try:
            ssh_channel.send(data)
        except Exception as e:
            print(f"Error sending to SSH: {e}")

@socketio.on('resize', namespace='/ssh')
def handle_ssh_resize(data):
    """Resize terminal"""
    global ssh_channel
    if ssh_channel and not ssh_channel.closed:
        try:
            ssh_channel.resize_pty(width=data['cols'], height=data['rows'])
        except Exception as e:
            print(f"Error resizing SSH pty: {e}")

def start_ssh_listener():
    """Background thread to read from SSH and emit to SocketIO"""
    global ssh_channel
    print("SSH Listener Started")
    
    while ssh_channel and not ssh_channel.closed:
        try:
            if ssh_channel.recv_ready():
                data = ssh_channel.recv(1024).decode('utf-8', errors='ignore')
                socketio.emit('output', data, namespace='/ssh')
            else:
                socketio.sleep(0.01)
        except Exception as e:
            print(f"SSH Read Error: {e}")
            break

def init_ssh_connection():
    global ssh_client, ssh_channel
    
    host = TRUENAS_HOST
    user = os.getenv('SSH_USER', 'root')
    
    # 讀取並解碼私鑰
    b64_key = os.getenv('SSH_PRIVATE_KEY_B64')
    password = os.getenv('SSH_PASSWORD')
    
    try:
        ssh_client = paramiko.SSHClient()
        ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        # 關鍵修改：從字串載入私鑰
        if b64_key:
            # 1. 解碼 Base64 回原本的 PEM/OpenSSH 格式
            key_str = base64.b64decode(b64_key).decode('utf-8')
            # 2. 轉換成 Paramiko 認得的 Key 物件
            # 嘗試檢測 Key 類型，預設嘗試 Ed25519，失敗則 RSA
            try:
                private_key = paramiko.Ed25519Key.from_private_key(io.StringIO(key_str))
            except:
                try:
                    private_key = paramiko.RSAKey.from_private_key(io.StringIO(key_str))
                except Exception as key_err:
                     print(f"Failed to load private key: {key_err}")
                     return

            # 3. 使用 pkey 參數連線
            print(f"Connecting with Private Key...")
            ssh_client.connect(host, username=user, pkey=private_key)
        else:
            if not password:
                print("SSH_PASSWORD or SSH_PRIVATE_KEY_B64 not set. Terminal will not function.")
                return
            # Fallback: 如果沒設 Key，試著用密碼
            print(f"Connecting with Password...")
            ssh_client.connect(host, username=user, password=password)

        
        ssh_channel = ssh_client.invoke_shell(term='xterm')
        
        # 延遲一點點時間讓 Shell 準備好
        socketio.sleep(0.5)

        # 傳送 Enter 喚醒 Shell，避免初始卡頓
        ssh_channel.send('\n')

        # Prompt 設定：
        # 1. 亮綠色 (%F{10}) User@Host
        # 2. 分隔符號保留 ":" (User 請求)
        # 3. 淺藍色 (%F{14}) Path，並透過變數替換確保 "/mnt" 顯示為 "~/mnt"
        # 需啟用 prompt_subst
        ssh_channel.send("setopt prompt_subst\n")
        
        # 複雜的 Zsh 變數替換邏輯：
        # ${PWD/#$HOME/~} -> 把開頭的 Home 路徑換成 ~
        # ${ ... /#\//~/ } -> 如果結果開頭還是 / (絕對路徑)，把 / 換成 ~/
        prompt_style = r"'%F{10}%n@%m%f:%F{14}${${PWD/#$HOME/~}/#\//~/}%f %# '"
        
        # 設定當前使用者的 Prompt
        ssh_channel.send(f"export PS1={prompt_style}\n")
        
        # 注入 sudo wrapper 函式
        # 使用 env 傳遞 PS1 並加入 -o prompt_subst
        sudo_wrapper = f"""
sudo() {{
    if [ "$1" = "-i" ]; then
        command sudo -i env PS1={prompt_style} zsh --no-rcs -o prompt_subst
    else
        command sudo "$@"
    fi
}}
"""
        ssh_channel.send(sudo_wrapper)
        ssh_channel.send("export TERM=xterm-256color\n")
        ssh_channel.send("clear\n")

        socketio.start_background_task(target=start_ssh_listener)
        
        print("SSH Connection Established")
    except Exception as e:
        print(f"SSH Connection Failed: {e}")

# Attempt to connect on startup
init_ssh_connection()



def _parse_smartctl_json(sj: dict, disk_name: str) -> dict:
    """Extract user-friendly fields from a smartctl -j JSON blob."""
    import math

    def _gb(b):
        if not b:
            return "—"
        tb = b / 1e12
        if tb >= 0.9:
            return f"{tb:.1f} TB"
        gb = b / 1e9
        return f"{gb:.0f} GB"

    # ---- health ----
    passed = None
    ss = sj.get("smart_status") or {}
    if "passed" in ss:
        passed = ss["passed"]
    # NVMe critical_warning → 0 means healthy
    nvme_log = sj.get("nvme_smart_health_information_log") or {}
    if passed is None and nvme_log:
        passed = (nvme_log.get("critical_warning", 1) == 0)

    # ---- device info ----
    model       = sj.get("model_name") or sj.get("model_family") or ""
    serial      = sj.get("serial_number") or ""
    firmware    = sj.get("firmware_version") or ""
    cap_bytes   = (sj.get("user_capacity") or {}).get("bytes") or 0
    form_factor = (sj.get("form_factor") or {}).get("name") or ""
    rotation    = sj.get("rotation_rate")
    if rotation == 0:
        media_type = "SSD"
    elif isinstance(rotation, int) and rotation > 0:
        media_type = f"HDD ({rotation} RPM)"
    else:
        media_type = "NVMe" if "nvme" in disk_name.lower() else "—"

    ata_version  = (sj.get("ata_version") or {}).get("string") or ""
    sata_version = (sj.get("sata_version") or {}).get("string") or ""
    interface    = sata_version or ata_version

    # ---- time-based stats ----
    power_on_h   = (sj.get("power_on_time") or {}).get("hours")
    power_cycles = sj.get("power_cycle_count")
    temp_c       = (sj.get("temperature") or {}).get("current")
    if temp_c is None and nvme_log:
        k = nvme_log.get("temperature")
        if k:
            temp_c = k - 273
    # Prefer SMART attribute 194 (Temperature_Celsius) raw value when available,
    # because TrueNAS /disk/temperatures also uses attr 194. The SCT temperature
    # returned in temperature.current can differ by ~10°C on some drives (e.g. Intel SSDs).
    # Note: some manufacturers pack min/max temps into the upper bytes of the 48-bit raw
    # value (e.g. 68719476769 = 0x10_0000_0021). The actual current temp is always in
    # the lowest 8 bits (& 0xFF). If that still looks bogus (> 100°C), fall back to
    # temperature.current.
    for entry in (sj.get("ata_smart_attributes") or {}).get("table") or []:
        if entry.get("id") == 194:
            raw194 = (entry.get("raw") or {}).get("value")
            if raw194 is not None:
                # Extract lowest byte for the actual current temperature
                t194 = int(raw194) & 0xFF
                if 0 < t194 < 100:
                    temp_c = t194
                elif temp_c is None:
                    # Last resort: trust the raw value if nothing else available
                    temp_c = t194
            break

    # ---- ATA SMART attributes ----
    key_attr_ids = {
        1:   "Raw Read Error Rate",
        5:   "Reallocated Sectors",
        9:   "Power-On Hours",
        177: "Wear Leveling Count",
        183: "Runtime Bad Blocks",
        187: "Reported Uncorrectable",
        194: "Temperature",
        196: "Reallocation Events",
        197: "Current Pending Sectors",
        199: "UDMA CRC Errors",
        231: "SSD Life Left (%)",
        241: "Total Host Writes (GiB)",
        242: "Total Host Reads (GiB)",
    }
    attrs = []
    for entry in (sj.get("ata_smart_attributes") or {}).get("table") or []:
        aid = entry.get("id")
        if aid not in key_attr_ids:
            continue
        raw_val = (entry.get("raw") or {}).get("value")
        # Attr 194: manufacturers pack min/max into upper bytes; mask to lowest byte
        if aid == 194 and raw_val is not None:
            raw_val = int(raw_val) & 0xFF
        value   = entry.get("value")
        worst   = entry.get("worst")
        thresh  = entry.get("thresh")
        failed  = entry.get("when_failed") or ""
        attrs.append({
            "id":      aid,
            "name":    key_attr_ids[aid],
            "value":   value,
            "worst":   worst,
            "thresh":  thresh,
            "raw":     raw_val,
            "failed":  failed,
        })

    # ---- NVMe specific ----
    nvme_attrs = []
    if nvme_log:
        mapping = [
            ("critical_warning",     "Critical Warning"),
            ("available_spare",      "Available Spare (%)"),
            ("percentage_used",      "Percentage Used (%)"),
            ("media_errors",         "Media Errors"),
            ("num_err_log_entries",  "Error Log Entries"),
            ("power_on_hours",       "Power-On Hours"),
            ("power_cycles",         "Power Cycles"),
        ]
        for key, label in mapping:
            v = nvme_log.get(key)
            if v is not None:
                nvme_attrs.append({"name": label, "raw": v})

    # ---- error log ----
    err_count = None
    elog = sj.get("ata_smart_error_log") or {}
    if "summary" in elog:
        err_count = elog["summary"].get("count", 0)
    elif nvme_log:
        err_count = nvme_log.get("num_err_log_entries", 0)

    # ---- last self-test ----
    last_test = None
    for section in ["ata_smart_self_test_log", "nvme_self_test_log"]:
        tlog = sj.get(section) or {}
        table = tlog.get("standard", {}).get("table") or tlog.get("table") or []
        if table:
            t = table[0]
            last_test = {
                "type":   t.get("type", {}).get("string") or t.get("type") or "",
                "status": t.get("status", {}).get("string") or t.get("status") or "",
                "hours":  t.get("lifetime_hours") or t.get("power_on_hours"),
            }
            break

    return {
        "disk":         disk_name,
        "model":        model,
        "serial":       serial,
        "firmware":     firmware,
        "capacity":     _gb(cap_bytes),
        "form_factor":  form_factor,
        "media_type":   media_type,
        "interface":    interface,
        "health_passed": passed,
        "temp":         temp_c,
        "power_on_h":   power_on_h,
        "power_cycles": power_cycles,
        "attrs":        attrs,
        "nvme_attrs":   nvme_attrs,
        "error_count":  err_count,
        "last_test":    last_test,
    }


def _shlex_quote(s: str) -> str:
    return shlex.quote(s)


def _ssh_exec(cmd: str, timeout: int = 30, user: str | None = None, password: str | None = None, sudo_password: str | None = None) -> tuple[str, str]:
    """Open a fresh exec channel via SSH and return (stdout, stderr).
    If sudo_password is provided, it will be written to stdin for sudo -S.
    """
    host = TRUENAS_HOST
    _user = user or os.getenv('SSH_USER', 'root')
    _password = password or os.getenv('SSH_PASSWORD')
    b64_key = os.getenv('SSH_PRIVATE_KEY_B64')

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        if b64_key:
            key_str = base64.b64decode(b64_key).decode('utf-8')
            try:
                pkey = paramiko.Ed25519Key.from_private_key(io.StringIO(key_str))
            except Exception:
                pkey = paramiko.RSAKey.from_private_key(io.StringIO(key_str))
            client.connect(host, username=_user, pkey=pkey, timeout=10)
        else:
            client.connect(host, username=_user, password=_password, timeout=10)

        stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
        if sudo_password:
            stdin.write(sudo_password + '\n')
            stdin.flush()
            stdin.channel.shutdown_write()
        out = stdout.read().decode('utf-8', errors='replace')
        err = stderr.read().decode('utf-8', errors='replace')
        return out, err
    finally:
        try:
            client.close()
        except Exception:
            pass


@app.route("/api/smart/<disk_name>")
def api_smart_disk(disk_name):
    import json as _json
    from flask import request as flask_request

    ssh_user = flask_request.headers.get("X-SSH-User", "").strip() or os.getenv("SSH_USER", "root")
    ssh_pass = flask_request.headers.get("X-SSH-Pass", "").strip()

    # Allow caller to force a specific smartctl device type (e.g. "sat", "sat,auto", "usbcypress")
    # Useful for SATA-over-USB bridges that need explicit SAT passthrough.
    forced_device_type = flask_request.args.get("device_type", "").strip()

    try:
        if not disk_name.startswith("/dev/"):
            dev_path = f"/dev/{disk_name}"
        else:
            dev_path = disk_name

        def run_smart(args_suffix: str) -> tuple[str, str]:
            if ssh_pass:
                # Use sudo -S -p '' to read password from stdin (no prompt output)
                cmd = f"sudo -S -p '' smartctl {args_suffix} {dev_path}"
                return _ssh_exec(cmd, timeout=30, user=ssh_user, password=ssh_pass, sudo_password=ssh_pass)
            else:
                cmd = f"sudo smartctl {args_suffix} {dev_path}"
                return _ssh_exec(cmd, timeout=30, user=ssh_user)

        # Check for auth failure in output
        def _auth_failed(out: str) -> bool:
            lower = out.lower()
            return "incorrect password" in lower or "authentication failure" in lower or \
                   ("sudo:" in lower and "password is required" in lower and "incorrect" in lower)

        def _smart_json_useful(sj: dict) -> bool:
            """Return True if the JSON blob contains meaningful SMART data."""
            if not sj:
                return False
            # smartctl exit_status: bit 1 set means "device not supported"
            exit_status = (sj.get("smartctl") or {}).get("exit_status", 0)
            if exit_status & 0x02:  # bit 1 = device open failed / unsupported
                return False
            ss = sj.get("smart_status") or {}
            has_status  = "passed" in ss
            has_attrs   = bool((sj.get("ata_smart_attributes") or {}).get("table"))
            has_nvme    = bool(sj.get("nvme_smart_health_information_log"))
            has_support = (sj.get("smart_support") or {}).get("available", True)
            return has_support and (has_status or has_attrs or has_nvme)

        # Build list of device type attempts:
        # If caller forced a type, try only that. Otherwise try default then common USB fallbacks.
        if forced_device_type:
            device_type_attempts = [forced_device_type]
        else:
            # "" = smartctl default, then SAT (covers most USB-SATA bridges)
            device_type_attempts = ["", "sat", "sat,auto"]

        smart_json = None
        for dtype in device_type_attempts:
            dtype_flag = f"-d {dtype} " if dtype else ""
            try:
                out, err = run_smart(f"{dtype_flag}--json -a")
                combined = out + err
                if _auth_failed(combined):
                    return jsonify({"auth_failed": True, "disk": disk_name}), 200
                if out.strip():
                    try:
                        candidate = _json.loads(out)
                        if _smart_json_useful(candidate):
                            smart_json = candidate
                            if dtype:
                                # Surface the device type used so the UI can show it
                                app.logger.info(f"smartctl: used -d {dtype} for {dev_path}")
                            break
                        elif smart_json is None:
                            # Keep the first result as last-resort fallback
                            smart_json = candidate
                    except Exception:
                        pass
            except Exception as e:
                app.logger.debug(f"smartctl JSON via SSH failed for {dev_path} (dtype={dtype!r}): {e}")

        if smart_json:
            parsed = _parse_smartctl_json(smart_json, disk_name)
            # Annotate with the device type hint used (helps UI surface the workaround)
            used_dtype = forced_device_type or next(
                (d for d in device_type_attempts if d and _smart_json_useful(smart_json)), ""
            )
            if used_dtype:
                parsed["device_type_hint"] = used_dtype
            return jsonify(parsed)

        # Attempt: plain text (last resort)
        for dtype in device_type_attempts:
            dtype_flag = f"-d {dtype} " if dtype else ""
            try:
                out, err = run_smart(f"{dtype_flag}-a")
                combined = out + err
                if _auth_failed(combined):
                    return jsonify({"auth_failed": True, "disk": disk_name}), 200
                text_out = out or err or "No output from smartctl"
                return jsonify({"disk": disk_name, "raw_text": text_out})
            except Exception as e:
                app.logger.debug(f"smartctl plain-text via SSH failed for {dev_path} (dtype={dtype!r}): {e}")

        return jsonify({"error": "smartctl returned no usable output", "disk": disk_name}), 502

    except Exception as exc:
        app.logger.error(f"SMART disk API Error [{disk_name}]: {exc}")
        return jsonify({"error": str(exc), "disk": disk_name}), 500


@app.route("/api/smart")
def api_smart():
    try:
        if not TRUENAS_HOST or not TRUENAS_API_KEY:
            return jsonify({"error": "Missing TRUENAS_HOST or TRUENAS_API_KEY"}), 500

        disks_info = _get_disk_info()
        if not disks_info:
            return jsonify({"disks": []})

        # Try to get SMART test results (may not be available on all versions)
        smart_results: dict[str, dict] = {}
        try:
            results = _fetch_truenas("/api/v2.0/smart/test/results")
            if isinstance(results, list):
                for r in results:
                    disk_name = r.get("disk")
                    if not disk_name:
                        continue
                    # Keep the most recent result per disk
                    if disk_name not in smart_results:
                        smart_results[disk_name] = r
        except Exception as e:
            app.logger.debug(f"SMART test results not available: {e}")

        enriched = []
        for disk in disks_info:
            name = disk.get("name", "")
            sr = smart_results.get(name, {})

            status = sr.get("status") or sr.get("result") or "N/A"
            test_type = sr.get("type") or sr.get("testtype") or ""
            # age string
            test_age = ""
            if sr.get("lifetime"):
                test_age = f"{sr['lifetime']}h runtime"

            enriched.append({
                "name": name,
                "model": disk.get("model", ""),
                "serial": disk.get("serial", ""),
                "size": disk.get("size", 0),
                "temp": disk.get("temp"),
                "type": disk.get("type", "HDD"),
                "smart_status": status,
                "smart_test_type": test_type,
                "smart_test_age": test_age,
            })

        return jsonify({"disks": enriched})

    except Exception as exc:
        app.logger.error(f"SMART API Error: {exc}")
        return jsonify({"error": str(exc)}), 500


@app.after_request
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type,Authorization'
    response.headers['Access-Control-Allow-Methods'] = 'GET,PUT,POST,DELETE,OPTIONS'
    return response

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5003, debug=True, allow_unsafe_werkzeug=True)

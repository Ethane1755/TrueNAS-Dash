# Based on TrueNAS API v25.10.2 specifications
from __future__ import annotations

import os
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import urlparse
import time
from functools import lru_cache
import concurrent.futures

import urllib3
import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template

load_dotenv()

app = Flask(__name__)

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
            timeout=2, # Reduced timeout for responsiveness
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
            timeout=3, # Reduced timeout
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
            timeout=1, # Very short timeout for Netdata (local/LAN)
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
        
    return result


@app.route("/")
def index() -> str:
    return render_template(
        "index.html",
        netdata_host=NETDATA_HOST,
        netdata_port=NETDATA_PORT,
        netdata_url=NETDATA_URL,
        spec_cpu=SPEC_CPU_MODEL,
        spec_ram=SPEC_RAM_TEXT,
        spec_pool1=SPEC_POOL1_TEXT,
        spec_pool2=SPEC_POOL2_TEXT,
        truenas_ip=TRUENAS_DISPLAY_IP,
        apps=APPS_CONFIG,
    )


@app.route("/api/metrics")
def api_metrics():
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            # Parallel Fetching
            f_cpu = executor.submit(_netdata_latest, NETDATA_CHART_CPU)
            f_ram = executor.submit(_netdata_latest, NETDATA_CHART_RAM)
            f_temp = executor.submit(_netdata_latest, NETDATA_CHART_CPU_TEMP)
            
            f_n1_chart = executor.submit(_netdata_latest, NETDATA_CHART_NET1) if NETDATA_CHART_NET1 else None
            f_n1_iface = executor.submit(_netdata_latest, f"net.{TRUENAS_INTERFACE_NET1}") if TRUENAS_INTERFACE_NET1 else None
            
            f_n2_chart = executor.submit(_netdata_latest, NETDATA_CHART_NET2) if NETDATA_CHART_NET2 else None
            f_n2_iface = executor.submit(_netdata_latest, f"net.{TRUENAS_INTERFACE_NET2}") if TRUENAS_INTERFACE_NET2 else None

            f_store_1 = executor.submit(_get_truenas_dataset_usage, "/mnt/storage", "storage (/mnt/storage)")
            f_store_2 = executor.submit(_get_truenas_dataset_usage, "/mnt/Apps", "Apps (/mnt/Apps)")

            cpu_latest = f_cpu.result()
            ram_latest = f_ram.result()
            temp_latest = f_temp.result()
            
            net1_chart_res = f_n1_chart.result() if f_n1_chart else None
            net1_iface_res = f_n1_iface.result() if f_n1_iface else None
            
            net2_chart_res = f_n2_chart.result() if f_n2_chart else None
            net2_iface_res = f_n2_iface.result() if f_n2_iface else None
            
            storage_disk = f_store_1.result()
            apps_disk = f_store_2.result()

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
                "system_ip": TRUENAS_DISPLAY_IP,
                "cpu_usage": cpu_usage,
                "cpu_temp": cpu_temp,
                "memory": memory,
                "disks": disks,
                "nets": nets,
            }
        )
    except requests.exceptions.RequestException as exc:
        return (
            jsonify(_format_request_error("Failed to reach Netdata", exc)),
            502,
        )
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": "Unexpected error", "details": str(exc)}), 500


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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5003, debug=True)

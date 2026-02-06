# TrueNAS Dashboard

A lightweight TrueNAS personal dashboard with a Flask proxy and a Tailwind UI.

## Setup

1. Install Python packages:

```bash
python -m pip install -r requirements.txt
```

2. Fill in the `.env` file:

```text
TRUENAS_HOST=192.168.1.xxx
TRUENAS_API_KEY=v2-xxxxxxxxxxxxxxxx
TRUENAS_SCHEME=https
TRUENAS_PORT=
TRUENAS_VERIFY_SSL=false
NETDATA_HOST=192.168.1.xxx
NETDATA_PORT=19999
NETDATA_URL=
NETDATA_SCHEME=http
NETDATA_VERIFY_SSL=true
NETDATA_BASE_PATH=
NETDATA_BEARER_TOKEN=
NETDATA_DATA_ENDPOINT=/api/v1/data
NETDATA_CHART_CPU=system.cpu
NETDATA_CHART_RAM=system.ram
NETDATA_CHART_DISK1=
NETDATA_CHART_DISK2=
NETDATA_CHART_NET1=
NETDATA_CHART_NET2=
NETDATA_LABEL_DISK1=Disk 1
NETDATA_LABEL_DISK2=Disk 2
NETDATA_LABEL_NET1=NIC 1
NETDATA_LABEL_NET2=NIC 2
TRUENAS_DISPLAY_IP=192.168.1.xxx
```

3. Start the Flask server:

```bash
python app.py
```

4. Open the dashboard in your browser:

```
http://localhost:1000
```

## Notes

- Netdata is configured via `NETDATA_HOST`/`NETDATA_PORT` or a full `NETDATA_URL`.
- If your Netdata requires auth, set `NETDATA_BEARER_TOKEN`.
- If Netdata is served under a sub-path, set `NETDATA_BASE_PATH`.
- If your API uses v3, set `NETDATA_DATA_ENDPOINT=/api/v3/data`.
- Metrics cards use `NETDATA_CHART_*` values; set them to your Netdata chart IDs.
- `TRUENAS_DISPLAY_IP` controls the system IP shown on the dashboard.

## Netdata discovery

Use these helper endpoints to find chart/context IDs:

- `http://localhost:1000/api/netdata/charts` (v1 charts)
- `http://localhost:1000/api/netdata/contexts` (v3 contexts)
- Logs are written to `logs/app.log` with rotation.

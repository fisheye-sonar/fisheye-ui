# Gateway sidecar setup

The sidecar is what makes the GPU worker sleep when idle and wake itself on
demand. Caddy still handles TLS/Basic Auth/reverse proxy exactly as it does
now. The sidecar is a separate small service alongside it, only reachable
from Caddy itself (bound to `127.0.0.1:9000`, never internet-facing).

## Deploying the sidecar

```bash
sudo mkdir -p /opt/fisheye-gateway-sidecar
sudo chown $USER:$USER /opt/fisheye-gateway-sidecar
cp sidecar/app.py sidecar/requirements.txt /opt/fisheye-gateway-sidecar/
cd /opt/fisheye-gateway-sidecar

python3 -m venv venv
venv/bin/pip install -r requirements.txt

# Fill in GPU_WORKER_INSTANCE_ID and GPU_WORKER_PRIVATE_IP before installing:
sudo cp /path/to/repo/deploy/gateway/fisheye-gateway-sidecar.service /etc/systemd/system/
sudo nano /etc/systemd/system/fisheye-gateway-sidecar.service   # replace the two REPLACE_ME values

sudo systemctl daemon-reload
sudo systemctl enable --now fisheye-gateway-sidecar
sudo systemctl status fisheye-gateway-sidecar
```

Verify it directly before wiring Caddy to it:
```bash
curl http://127.0.0.1:9000/gateway-status
```

## Caddyfile changes needed

Two things have to be added to the existing Caddyfile: routing
`/gateway-status` and `/gateway-wake` to the sidecar instead of the GPU
worker, and enabling access logging (the idle-watcher reads Caddy's own
access log to find the timestamp of the last real request, rather than
tracking activity itself).

```
your-hostname {
	basic_auth {
		username $YourExistingHashHere
	}

	@sidecar path /gateway-status /gateway-wake
	handle @sidecar {
		reverse_proxy 127.0.0.1:9000
	}

	handle {
		reverse_proxy GPU_WORKER_PRIVATE_IP:8000
	}

	log {
		output file /var/log/caddy/access.log
		format json
	}
}
```

`basic_auth` stays at the top level so it applies to everything, including
the sidecar routes - nobody should be able to trigger a wake (which costs
real GPU-hours) without valid credentials. The `@sidecar` matcher routes
just those two paths to the sidecar; everything else still proxies to the
GPU worker as before.

After editing, same as always:
```bash
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

## Known gap

The idle-watcher's activity signal (Caddy's access log) only sees traffic
*after* the worker is already awake - a job that's still running with no
new HTTP requests for a while (e.g. a long inference job with the browser
tab just sitting on a progress bar, no polling) could look idle even though
work is actually happening. The WebSocket progress stream itself counts as
an open connection Caddy logs, so this should hold in practice, but worth
confirming once a real long job is tested through this path.
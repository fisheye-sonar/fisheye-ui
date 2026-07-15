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

Also copy the static wake page next to it - Caddy serves this directly off
disk, not through the sidecar process, so it stays reachable even if the
sidecar were ever down too:
```bash
sudo mkdir -p /opt/fisheye-gateway-sidecar/static
sudo cp /path/to/repo/deploy/gateway/static/waking.html /opt/fisheye-gateway-sidecar/static/
```

## Caddyfile changes needed

The app itself (the React frontend, `/jobs`, everything) is served *by the
GPU worker*, so while it's asleep, Caddy's normal reverse proxy to it just
fails - there's nothing on the other end to answer. The fix is a
`handle_errors` block: when the proxy to the GPU worker comes back
unreachable, Caddy instead serves a small static page that polls
`/gateway-status`, triggers `/gateway-wake`, and reloads once the worker
answers again - at which point the normal proxy succeeds and the real app
loads.

Two things have to be added to the existing Caddyfile: routing
`/gateway-status` and `/gateway-wake` to the sidecar instead of the GPU
worker, and the `handle_errors` fallback to the wake page. (Access logging
is optional now - the idle-watcher gets its activity signal from the GPU
worker's own job state via `/jobs/active`, not from Caddy's log, so `log {}`
below is just for general debugging if you want it.)

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
		reverse_proxy GPU_WORKER_PRIVATE_IP:8000 {
			fail_duration 10s
		}
	}

	handle_errors {
		@unreachable expression `{http.error.status_code} in [502, 503, 504]`
		handle @unreachable {
			root * /opt/fisheye-gateway-sidecar/static
			rewrite * /waking.html
			file_server
		}
	}
}
```

`basic_auth` stays at the top level so it applies to everything, including
the sidecar routes and the wake page - nobody should be able to trigger a
wake (which costs real GPU-hours) without valid credentials. The
`@sidecar` matcher routes just those two paths to the sidecar; everything
else still proxies to the GPU worker as before, falling back to the wake
page only when that proxy fails.

After editing, same as always:
```bash
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

## Wake page

`static/waking.html` is a small, dependency-free HTML/JS page (no build
step - deploy it as-is) that Caddy falls back to whenever the GPU worker is
unreachable. On load it:

1. `GET /gateway-status`. If `asleep`, immediately `POST /gateway-wake` to
   start the instance.
2. Polls `/gateway-status` every 3s, showing a "waking up" message while
   state is `starting`.
3. Once state is `ready`, reloads the page - the real app loads normally
   from there since the GPU worker is answering again.
4. If the sidecar's own wake attempt times out (state goes back to
   `asleep` after having been `starting`), shows an error with a "Try
   again" button rather than polling forever.

Since `basic_auth` wraps the whole site, a user only ever sees this page
after already authenticating - so the wake happens automatically as soon
as someone logs in and hits an asleep worker, with no separate action
needed.

## Idle detection

The idle-watcher's activity signal is the GPU worker's own job state via
`GET /jobs/active` (`{"active": bool, "idle_seconds": float | null}`), not
HTTP traffic. The rule:

- A job is pending/running -> never stop, regardless of how long it's
  been running or how long since the last request.
- No job running -> idle time is measured from when the *most recent job
  finished* (`idle_seconds`). A user composing the form, or just reading a
  completed job's results with the tab open, isn't "activity" - only job
  start/finish moves the clock.
- No job has ever run yet this wake cycle (`idle_seconds` is `null`) -> the
  sidecar falls back to time since the worker became `ready`.
- The worker can't be reached to ask -> treated as "don't know," not as
  "no active jobs," so a transient network blip can't cause a stop
  mid-job.

This intentionally ignores raw HTTP traffic (Caddy access log, WebSocket
connections, page views) entirely - an early version of this used Caddy's
access log as the signal instead, which broke in practice: a user with the
tab open but not actively submitting/polling anything (e.g. composing a
long form) generated no requests at all, so the idle clock kept advancing
even though someone was actively using the page, and the worker could get
stopped out from under them. Tying the clock to job lifecycle events
instead of network activity avoids that class of problem entirely.

After calling `stop_instances`, the sidecar polls AWS until the instance
actually reports `stopped` (up to `STOP_TIMEOUT_SECONDS`, default 120s)
before marking state `asleep`. This matters because AWS instances sit in a
transitional `stopping` state for a bit first - a wake triggered in that
window fails with `IncorrectInstanceState` if the sidecar has already
optimistically called itself asleep. `_wake_worker` also retries through
that same error as a second line of defense, in case the instance is
stopped by something other than this idle-watcher.
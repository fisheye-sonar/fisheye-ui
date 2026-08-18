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

Also copy the static wake page and login page (and the shared logo) next to
it - Caddy serves these directly off disk, not through the sidecar process,
so they stay reachable even if the sidecar were ever down too:
```bash
sudo mkdir -p /opt/fisheye-gateway-sidecar/static
sudo cp /path/to/repo/deploy/gateway/static/waking.html /opt/fisheye-gateway-sidecar/static/
sudo cp /path/to/repo/deploy/gateway/static/login.html /opt/fisheye-gateway-sidecar/static/
sudo cp /path/to/repo/deploy/gateway/static/fisheye_blue_combined.svg /opt/fisheye-gateway-sidecar/static/
```

Before wiring Caddy to it, generate the two secrets `/allowlist` and
`/login` need and set them in `fisheye-gateway-sidecar.service`
(`GATEWAY_ADMIN_SECRET`, `GATEWAY_SESSION_SECRET` - e.g. `openssl rand -hex
32` for each), then restart the sidecar:
```bash
sudo systemctl restart fisheye-gateway-sidecar
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

Auth works the same way, one level up: Caddy's `forward_auth` calls the
sidecar's `GET /verify` on every request. A 200 (with `X-Fisheye-User` set)
lets the request through; a 401 - caught by another `handle_errors` block -
sends the browser to the login page instead. Nobody, including a `/gateway-
wake` request, reaches the sidecar's wake logic or the GPU worker without a
valid session, so the "no wake without valid credentials" property (real
money - GPU-hours) holds exactly as it did under `basic_auth`. (Access
logging is optional now - the idle-watcher gets its activity signal from the
GPU worker's own job state via `/jobs/active`, not from Caddy's log, so
`log {}` below is just for general debugging if you want it.)

```
your-hostname {
	# Unauthenticated on purpose - this is what forward_auth sends people
	# to on a 401, so it can't itself require auth.
	@login path /login /login.html /fisheye_blue_combined.svg
	handle @login {
		root * /opt/fisheye-gateway-sidecar/static
		rewrite /login /login.html
		reverse_proxy /login 127.0.0.1:9000
		file_server
	}

	handle {
		forward_auth 127.0.0.1:9000 {
			uri /verify
			copy_headers X-Fisheye-User
		}

		@sidecar path /gateway-status /gateway-wake
		handle @sidecar {
			reverse_proxy 127.0.0.1:9000
		}

		reverse_proxy GPU_WORKER_PRIVATE_IP:8000 {
			fail_duration 10s
		}
	}

	handle_errors {
		@unauthenticated expression `{http.error.status_code} == 401`
		handle @unauthenticated {
			redir /login 302
		}

		@unreachable expression `{http.error.status_code} in [502, 503, 504]`
		handle @unreachable {
			root * /opt/fisheye-gateway-sidecar/static
			rewrite * /waking.html
			file_server
		}
	}
}
```

(The `reverse_proxy /login 127.0.0.1:9000` line inside the `@login` handler
is what routes the login *form's POST* to the sidecar's `POST /login` -
everything else matched by `@login`, i.e. `GET /login` and the static
assets, falls through to `file_server` instead. Validate the exact matcher
precedence with `caddy validate` before reloading, same as always.)

`copy_headers X-Fisheye-User` is what forwards the session's verified email
to the app, which is what lets it enforce a per-account job limit (10 jobs
per email by default, persisted across sessions - see `fisheye_ui/usage.py`).
Set `FISHEYE_UI_UNLIMITED_USER` in `fisheye-ui.service` on the GPU worker to
whichever email should be exempt (e.g. an internal team account added
through the allowlist like anyone else); every other email is capped. A
request with no `X-Fisheye-User` header (e.g. local/desktop use, which has
no Caddy in front at all) is never limited.

Provisioning a new person no longer means editing the Caddyfile at all - see
"Google Form setup" below. `caddy hash-password` and per-person Caddyfile
entries are gone; `basic_auth` isn't used anymore.

After editing, same as always:
```bash
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

## Google Form setup (self-serve access requests)

Access is now self-serve: a public Google Form collects an email address,
and a bound Apps Script emails that person a one-time access code and tells
the sidecar to allow it in - no SSH, no Caddyfile edit, no reload.

1. Create a Google Form with a single required short-answer field labeled
   "Email" - don't turn on "Restrict to users in domain" or "Collect email
   addresses" (both require the respondent to already have a Google
   account, which defeats the point).
2. In the Form's editor, open **Extensions -> Apps Script** and replace the
   default content with:

   ```javascript
   const SIDECAR_URL = "https://your-hostname/allowlist"; // through Caddy, not directly to :9000
   const ADMIN_SECRET = PropertiesService.getScriptProperties().getProperty("ADMIN_SECRET");

   function onFormSubmit(e) {
     const email = e.response.getItemResponses()[0].getResponse().trim().toLowerCase();
     const code = Utilities.getUuid().split("-")[0]; // short, typeable

     GmailApp.sendEmail(
       email,
       "Your FishEye demo access code",
       `Code: ${code}\n\nSign in at https://your-hostname/login with this email and code.`
     );

     UrlFetchApp.fetch(SIDECAR_URL, {
       method: "post",
       contentType: "application/json",
       headers: { "X-Admin-Secret": ADMIN_SECRET },
       payload: JSON.stringify({ email: email, code: code }),
     });
   }
   ```

3. In **Project Settings -> Script Properties**, add `ADMIN_SECRET` set to
   the same value as `GATEWAY_ADMIN_SECRET` in
   `fisheye-gateway-sidecar.service` - keeping it out of the script source
   means it isn't exposed if the script is ever shared/copied.
4. Under **Triggers**, add one for `onFormSubmit`, event source "From
   form", event type "On form submit".
5. Test it: submit the Form yourself, confirm the email arrives, then sign
   in at `/login` with that email/code.

Losing a code doesn't require any admin action - resubmitting the Form
overwrites that email's entry in the allowlist with a fresh code (see
`POST /allowlist` in `sidecar/app.py`, which upserts).

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

Since `forward_auth` wraps the whole site (see "Caddyfile changes needed"
above), a user only ever sees this page after already authenticating - so
the wake happens automatically as soon as someone logs in and hits an
asleep worker, with no separate action needed.

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
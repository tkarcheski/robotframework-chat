# LAN cluster setup

**Use SSH to manage private LAN hosts, Ollama for shared inference, and
Unsloth Studio on the controller. Keep every inference endpoint off the public
internet.**

This guide creates a small, repeatable cluster for running this repository's
model tests. It uses placeholder names and addresses. Replace them with your
own inventory.

## Plain version

1. Give every host a stable name and address.
2. Enable SSH and install a controller key on each worker.
3. Run Ollama only on hosts that serve models, and expose it only to the LAN.
4. Run Unsloth Studio as a localhost-only user service on the controller.
5. Record Ollama endpoints in `host-config.toml`, then verify before scheduling.

## Cluster roles

| Role | Example name | Runs | Network exposure |
|---|---|---|---|
| Controller | `rfc-controller` | Robot runs, scheduler, Unsloth Studio, optional Superset | SSH on LAN. Studio on localhost. |
| Ollama worker | `ollama-a` | Ollama models | TCP `11434` on trusted LAN only. |
| Ollama worker | `ollama-b` | Ollama models | TCP `11434` on trusted LAN only. |
| Database host | `rfc-db` | PostgreSQL, optional Superset | Only required ports on the trusted LAN. |

Reserve a DHCP address or configure a static address for every host. Put names
in local DNS, or use mDNS names such as `ollama-a.local`. Changing addresses
breaks scheduled runs and makes audit results hard to trace.

## 1. Enable SSH

Install and enable OpenSSH on every Linux host:

```bash
sudo systemctl enable --now sshd.service
systemctl is-active sshd.service
```

On macOS, enable **Remote Login** in System Settings, or run:

```bash
sudo systemsetup -setremotelogin on
```

Create a dedicated controller key if one does not exist:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519 -C "$(whoami)@$(hostname)"
```

Before trusting a new host, compare its SSH fingerprint through a trusted
channel. Then install the public key for each worker account:

```bash
ssh-copy-id worker@ollama-a.local
ssh-copy-id worker@ollama-b.local
ssh -o BatchMode=yes worker@ollama-a.local hostname
ssh -o BatchMode=yes worker@ollama-b.local hostname
```

`ssh-copy-id` is commonly available on Linux. On macOS controllers, use the
same public key with the host's normal SSH key-install procedure. Do not put
passwords in shell history, committed files, or agent prompts.

Confirm the controller is reachable from another LAN host:

```bash
ssh controller@rfc-controller.local hostname
```

## 2. Configure Ollama workers

Install Ollama and pull the models assigned to each worker. A worker must serve
the model before the scheduler can use it:

```bash
ollama pull qwen3:32b
ollama list
```

Bind Ollama to the LAN only when other trusted hosts need it. For Linux,
override the systemd service:

```bash
sudo systemctl edit ollama.service
```

```ini
[Service]
Environment="OLLAMA_HOST=0.0.0.0:11434"
```

```bash
sudo systemctl daemon-reload
sudo systemctl restart ollama.service
```

Allow TCP `11434` only from the private subnet in the host firewall. Ollama has
no built-in authentication. A public bind exposes every installed model to
anyone who can reach the port.

From the controller, verify each worker before adding it to the inventory:

```bash
curl --fail http://ollama-a.local:11434/api/tags
curl --fail http://ollama-b.local:11434/api/tags
```

To discover known hosts on a trusted network, scan only the intended subnet:

```bash
nmap -n -Pn --open -p 22,11434 192.168.1.0/24
```

No response on `11434` means the host is not an Ollama worker, the service is
localhost-only, or a firewall blocks the port. Do not assume that an SSH host
also serves models.

## 3. Add the worker inventory

Copy the template, then record only tested endpoints:

```bash
cp host-config.toml.example host-config.toml
```

```toml
[[hosts]]
name = "ollama-a"
endpoint = "http://ollama-a.local:11434"
priority = 20
max_parallel = 1
skip_models = []

[[hosts]]
name = "ollama-b"
endpoint = "http://ollama-b.local:11434"
priority = 10
max_parallel = 1
skip_models = ["large-model-that-does-not-fit"]

[defaults]
connect_timeout = 2
request_timeout = 5
global_max_parallel = 2
```

`host-config.toml` is git-ignored because it describes private infrastructure.
It is the source of truth for curated fleet runs:

```bash
make discover-local-models
make run-local-models
```

Set `max_parallel` conservatively. Parallel requests multiply context memory.
An aggressive value turns an otherwise healthy worker into a timeout source.

## 4. Run Unsloth Studio on the controller

Unsloth Studio is useful for local model management and OpenAI-compatible API
experiments. It is not an Ollama worker. Keep its web UI bound to localhost and
reach it remotely through SSH forwarding.

Create `~/.config/systemd/user/unsloth-studio.service`:

```ini
[Unit]
Description=Unsloth Studio
After=network.target

[Service]
Type=simple
ExecStart=%h/.local/bin/unsloth studio --host 127.0.0.1 --port 8888
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
```

Enable it and preserve the user service after logout:

```bash
systemctl --user daemon-reload
systemctl --user enable --now unsloth-studio.service
loginctl enable-linger "$USER"
systemctl --user status unsloth-studio.service
```

Open the UI locally at `http://127.0.0.1:8888`. From another machine, use an
SSH tunnel:

```bash
ssh -L 8888:127.0.0.1:8888 controller@rfc-controller.local
```

Then open `http://127.0.0.1:8888` in the remote browser. Do not add
`--api-only` when the UI is required. Do not add `--silent` to a systemd unit.
Journal logs are the fastest way to diagnose startup failures:

```bash
journalctl --user -u unsloth-studio.service -f
```

## 5. Add Superset and the database

Run the database and Superset stack from the controller or a dedicated database
host. Follow [SUPERSET_SETUP.md](SUPERSET_SETUP.md) for the full bootstrap.

Use a private `.env` with unique database and Superset passwords. Keep the
database on a private network. If Superset needs LAN access, terminate HTTPS
and authentication at a trusted reverse proxy. Never publish the database port
or Ollama directly to the internet.

After bootstrap, verify the services and test-result freshness:

```bash
docker compose ps --all
curl --fail http://127.0.0.1:8088/health
psql "$DATABASE_URL" -c "SELECT MAX(timestamp) FROM test_runs"
```

## Verification checklist

Run these checks before a multi-host evaluation:

```bash
# Controller
systemctl is-active sshd.service
systemctl --user is-active unsloth-studio.service

# Each Ollama worker
curl --fail http://ollama-a.local:11434/api/tags
curl --fail http://ollama-b.local:11434/api/tags

# Repository
make discover-local-models
make robot-dryrun
```

Record the exact host name, endpoint, model tag, digest, quantization, and
harness revision for every run. An endpoint that answers without this provenance
cannot support a reproducible comparison.

## The gap

This guide sets up a trusted LAN cluster. It does not provide internet exposure,
central identity management, TLS termination, secrets rotation, or high
availability. Add those before treating the cluster as shared production
infrastructure.

# Deploying Trim

Trim runs as one Docker Compose stack on a single small Linux server:

```
Internet ──443──▶ Caddy (HTTPS, auto certificate) ──▶ nginx (dashboard + /api proxy) ──▶ FastAPI
                                                                                          │
                                                       worker (sync every 15 min) ──▶ PostgreSQL
```

Only ports 22, 80 and 443 are open. PostgreSQL and the API are never reachable from the internet.

## 1. Get a server (pick one)

| Option | Cost | Server | Free domain name |
|---|---|---|---|
| **Azure for Students** (sign up with your school email) | $100 credit, no card | Ubuntu 24.04, size B2s (2 vCPU, 4 GB); B1ms (2 GB) also works | Yes: set a *DNS name label* on the VM's public IP → `yourname.francecentral.cloudapp.azure.com` |
| **Hetzner Cloud** | CX23, €5.99/month (2 vCPU, 4 GB) | Ubuntu 24.04 | No: use a free [DuckDNS](https://www.duckdns.org) name pointing at the server IP |

* **Azure:** when creating the VM, choose SSH key authentication and allow inbound ports **SSH, HTTP, HTTPS**. Check the size's monthly price against your credit in the Azure pricing calculator.
* **Hetzner:** this is a purchase, so put about €30 (October to February) in the project's provisional budget and get approval first, as the project guide requires.

## 2. Put the code on GitHub

```bash
cd trim
git remote add origin https://github.com/<you>/trim.git
git push -u origin main
```

A public repository is fine: there are no secrets in the code (`.env` is git-ignored and CI scans for leaks). For a private repository, copy the zip to the server with `scp` instead of cloning.

## 3. Install (one command)

```bash
ssh <user>@<server-ip>
git clone https://github.com/<you>/trim.git && cd trim
sudo ./deploy/setup.sh <your-domain>        # e.g. trim-esaip.francecentral.cloudapp.azure.com
```

The script:
* installs Docker;
* adds swap on small servers;
* enables the firewall (22, 80 and 443 only);
* generates every secret into a root-only `.env`;
* builds and starts the stack, and loads the 40-person test organisation.

It prints the **admin token once**. Save it, then open `https://<your-domain>` and sign in with it. The first build takes about 5 to 10 minutes, and the HTTPS certificate is issued automatically within a minute of first start.

## 4. Day-to-day operations

Shortcut used below (add it to `~/.bashrc` on the server):

```bash
alias dc='sudo docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml'
```

| Task | Command |
|---|---|
| Deploy a new version (migrations run automatically) | `git pull && dc up -d --build` |
| Refresh the demo data before a presentation | `dc run --rm api trim simulate --reset` |
| Give a teammate access | `dc run --rm api trim token create --name sreeja --role reviewer`, then append the printed entry to `TRIM_API_TOKENS` in `.env` (comma-separated) and run `dc up -d` |
| See logs | `dc logs -f api` (or `worker`, `web`, `caddy`) |
| Back up the database | `dc exec db pg_dump -U trim trim > backup-$(date +%F).sql` |
| Status | `dc ps` |

Roles:
* `admin` can trim, undo and decide requests;
* `reviewer` is read-only and can review alerts;
* `service` is for an agent submitting permission requests through the API.

## 5. Connect a real Google Workspace test tenant (optional)

Follow "Connecting a real Google Workspace test tenant" in the README, then:

```bash
dc run --rm -T api trim connect google --credentials /dev/stdin < sa-key.json
shred -u sa-key.json                           # the key now lives encrypted in the database
# in .env: TRIM_CONNECTOR=google and TRIM_GOOGLE_ADMIN_EMAIL=admin@your-test-domain
dc up -d
```

## Security checklist

* [ ] SSH with keys only (password login disabled)
* [ ] `.env` never committed or shared; it is the only place secrets live
* [ ] Admin token stored in a password manager; give teammates their own `reviewer` tokens
* [ ] Back up the database before every demo
* [ ] `dc up -d --build` after pulling security updates (CI runs dependency audits on every push)

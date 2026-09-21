# Proxmox LXC diegimas

Pilnas kontekstas: [Kelionių planavimo agentinė sistema](https://claude.ai/code/artifact/147e64cc-db43-43dd-a08c-263438c75677) → skyrius „Centrinė valdymo konsolė“.

## Konteineris

- Unprivileged LXC, Debian 12 šablonas
- 2 vCPU, 2 GB RAM, 16 GB diskas
- Be `nesting`, be GPU
- Statinis IP LAN'e (pvz. `192.168.1.50`)

## Diegimas

```bash
apt update && apt install -y python3-venv git caddy

# Anthropic CLI ir prisijungimas (profilis ~/.config/anthropic/, be env kintamųjų)
curl -fsSL https://cli.anthropic.com/install.sh | sh
ant auth login

git clone https://github.com/sauliusc/travel-agent /opt/travel-agent
cd /opt/travel-agent
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# GitHub token — systemd credential, ne .env
mkdir -p /etc/travel-agent
echo "github_pat_..." > /etc/travel-agent/github_token
chmod 600 /etc/travel-agent/github_token
```

## systemd servisas

`/etc/systemd/system/travel-console.service`:

```ini
[Unit]
Description=Travel planning console
After=network.target

[Service]
WorkingDirectory=/opt/travel-agent
LoadCredential=github_token:/etc/travel-agent/github_token
ExecStart=/opt/travel-agent/.venv/bin/uvicorn console.app:app --host 127.0.0.1 --port 8000
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

Kode token'as skaitomas iš `$CREDENTIALS_DIRECTORY/github_token`.

## Caddy

`/etc/caddy/Caddyfile`:

```
:80 {
    basicauth {
        saulius <caddy hash-password rezultatas>
    }
    reverse_proxy 127.0.0.1:8000
}
```

```bash
systemctl enable --now travel-console caddy
```

Konsolė pasiekiama `http://192.168.1.50/` tik iš namų tinklo. Jei reikia iš išorės — per Tailscale/WireGuard, ne port forwarding.

## Priežiūra

- Proxmox snapshot prieš `pip install --upgrade anthropic` (major versijos keičia API)
- `journalctl -u travel-console -f` — agentų žurnalai
- SQLite failas `/opt/travel-agent/console.db` — įtraukti į Proxmox backup

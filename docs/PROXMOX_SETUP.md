# Proxmox LXC diegimas

Pilnas kontekstas: [Kelionių planavimo agentinė sistema](https://claude.ai/code/artifact/147e64cc-db43-43dd-a08c-263438c75677) → skyrius „Centrinė valdymo konsolė“.

## Konteineris

- Unprivileged LXC, Debian 12 šablonas
- 2 vCPU, 2 GB RAM, 16 GB diskas
- Be `nesting`, be GPU
- Statinis IP LAN'e (pvz. `192.168.1.50`)

## Diegimas — vienas komandos paleidimas (rekomenduojama)

Konteineryje, prisijungus kaip `root`:

```bash
curl -fsSL https://raw.githubusercontent.com/sauliusc/travel-agent/main/scripts/install.sh | bash
```

Scenarijus (`scripts/install.sh`):
- įdiegia sistemos paketus (Python, git, Caddy)
- klonuoja/atnaujina `/opt/travel-agent`, sukuria venv, įdiegia priklausomybes
- įdiegia `ant` CLI (Anthropic prieigai)
- interaktyviai paklausia credential'ų ir įrašo į `/etc/travel-agent/credentials.env`
  (600, žr. `.env.example` visų laukų sąrašui) — **vienintelė vieta**, kur jie laikomi
- įdiegia ir paleidžia `travel-console` systemd servisą bei Caddy su basic auth

Idempotentiškas — saugu paleisti pakartotinai (pvz. po `git pull`, kad atsinaujintų
kodas). Jei nori pakeisti credential'us: `bash scripts/install.sh --reconfigure`.

Jei pasirinkai `ant auth login` variantą credential'ų klausimyne, po scenarijaus
paleidimo dar reikia:

```bash
ant auth login
systemctl restart travel-console
```

## Diegimas — rankiniu būdu (jei nori suprasti kiekvieną žingsnį)

```bash
apt update && apt install -y python3-venv git caddy

# Anthropic CLI ir prisijungimas (profilis ~/.config/anthropic/, be env kintamųjų)
curl -fsSL https://cli.anthropic.com/install.sh | sh
ant auth login

git clone https://github.com/sauliusc/travel-agent /opt/travel-agent
cd /opt/travel-agent
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

mkdir -p /etc/travel-agent && chmod 700 /etc/travel-agent
cp .env.example /etc/travel-agent/credentials.env
# ... užpildyti GITHUB_TOKEN, GITHUB_OWNER, CONSOLE_BASIC_AUTH_* rankiniu būdu ...
chmod 600 /etc/travel-agent/credentials.env

cp deploy/travel-console.service /etc/systemd/system/
systemctl daemon-reload

caddy hash-password --plaintext '<slaptažodis>'   # įklijuoti į Caddyfile
cp deploy/Caddyfile.template /etc/caddy/Caddyfile
# ... pakeisti __CONSOLE_BASIC_AUTH_USER__ ir __CONSOLE_BASIC_AUTH_HASH__ ...

systemctl enable --now travel-console caddy
```

`console/config.py` pats nuskaito `/etc/travel-agent/credentials.env` paleidimo metu —
jokio `EnvironmentFile=` ar `LoadCredential=` systemd unit'e nereikia, tik teisė skaityti
tą failą.

Konsolė pasiekiama `http://192.168.1.50/` tik iš namų tinklo. Jei reikia iš išorės — per Tailscale/WireGuard, ne port forwarding.

## Priežiūra

- Proxmox snapshot prieš `pip install --upgrade anthropic` (major versijos keičia API)
- `journalctl -u travel-console -f` — agentų žurnalai (paleidimo metu čia matysi ir
  credential'ų patikros įspėjimus, jei kažko trūksta)
- SQLite failas `/opt/travel-agent/console.db` — įtraukti į Proxmox backup
- Credential'ai laikomi tik `/etc/travel-agent/credentials.env` (600) — niekada
  repozitorijoje, niekada `.bash_history`

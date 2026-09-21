# travel-agent

Agentinė kelionių planavimo sistema — nuo laisvo teksto reikalavimų iki paruošto
kelionės puslapio GitHub Pages, automatiškai.

Sistema paremta patirtimi iš [`albania-3days-trip`](https://github.com/sauliusc/albania-3days-trip)
ir [`biezcady-7days-trip`](https://github.com/sauliusc/biezcady-7days-trip) projektų, kuriuose
rankiniu būdu buvo atrastos tokios logistikos klaidos kaip nenavigacinis kelias (bekelė) ar
neteisingi važiavimo laikai.

## Architektūra

Pilnas sistemos dizainas (14 agentų, jų sąveika, techniniai reikalavimai, setup instrukcijos,
centrinė valdymo konsolė, Proxmox diegimas):
**[Kelionių planavimo agentinė sistema](https://claude.ai/code/artifact/147e64cc-db43-43dd-a08c-263438c75677)**

Trumpai:

```
Vartotojas → Orchestrator → [Requirements, Research, Logistics Validator, Accommodation]
                          → Itinerary Planner → [Map, Image, Budget]
                          → Page Designer → Review/Critic → CI/CD → GitHub Pages
```

## Katalogų struktūra

```
travel-agent/
├── agents/         # kiekvieno agento modulis (run_agent() kvietimai)
├── tools/          # @beta_tool funkcijos (OSRM, Overpass, Wikimedia, GitHub API)
├── schemas/        # Pydantic modeliai agentų JSON išvestims
├── prompts/        # system prompt .md failai kiekvienam agentui
├── templates/       # Page Designer HTML/workflow šablonai
├── console/         # FastAPI valdymo konsolė (paste-and-go UI)
├── docs/            # diegimo dokumentacija (Proxmox ir kt.)
└── orchestrator.py  # pagrindinis srautas
```

## Statusas

Sistema kuriama palaipsniui — kiekvienas komponentas turi atskirą GitHub issue ir yra
implementuojamas atskirame PR (`claude/*` šakos, automatiškai sujungiamos į `main` po CI).
Žr. [Issues](https://github.com/sauliusc/travel-agent/issues).

## Setup

### Proxmox LXC (vienas komandos paleidimas)

```bash
curl -fsSL https://raw.githubusercontent.com/sauliusc/travel-agent/main/scripts/install.sh | bash
```

Įdiegia viską (sistema, Python, venv, `ant` CLI, systemd servisą, Caddy), paklausia
credential'ų ir juos saugo vienoje vietoje — `/etc/travel-agent/credentials.env` (600).
Pilnos instrukcijos: `docs/PROXMOX_SETUP.md`.

### Lokalus vystymas

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env   # užpildyti GITHUB_TOKEN ir kt. — console/config.py nuskaito automatiškai
ant auth login          # arba ANTHROPIC_API_KEY faile .env
```

Visi reikalingi credential'ai ir jų paskirtis aprašyti `.env.example`.

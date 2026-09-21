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

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Anthropic prieiga (rekomenduojama)
ant auth login

# GitHub prieiga CI/CD Agentui
export GITHUB_TOKEN="github_pat_..."
```

Pilnos diegimo instrukcijos (įskaitant Proxmox LXC): `docs/PROXMOX_SETUP.md`.

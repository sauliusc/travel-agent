# CLAUDE.md

Šis projektas implementuoja agentinę kelionių planavimo sistemą, aprašytą
[dizaino dokumente](https://claude.ai/code/artifact/147e64cc-db43-43dd-a08c-263438c75677).

## Kontekstas

Sistema pakeičia rankinį kelionės puslapių kūrimo procesą, naudotą projektuose
`albania-3days-trip` ir `biezcady-7days-trip`. Ten paaiškėjo, kad kritiškiausia dalis yra
**logistikos validacija** — pvz. SH74 kelias Albanijoje pasirodė esantis bekelė, netinkama
standartiniam nuomotam automobiliui, o pirminis planas to nepastebėjo.

## Agentai

14 agentų, aprašyti dizaino dokumente: Orchestrator, Requirements Analyst, Research,
Logistics Validator, Accommodation, Itinerary Planner, Map, Image, Page Designer, Budget,
Weather/Season, Review/Critic, Documentation, CI/CD.

## Technologijos

- **Python 3.10+**. Agentai veikia per **Claude Code CLI** (`claude -p`, headless/print
  mode) subprocess kvietimais (`agents/base.py`), autentifikacija — **prenumeratos**
  `claude auth login` (claude.ai Pro/Max), **ne** API raktas. Priežastis: atskira
  `claude-agent-sdk` biblioteka aiškiai reikalauja API rakto ir draudžia prenumeratos
  autentifikaciją trečiųjų šalių produktams — bet `claude -p` yra oficialus, palaikomas
  Claude Code būdas prenumeratoriui automatizuoti savo asmeninį naudojimą (skiriasi nuo
  Agent SDK).
- Custom "įrankiai" (`tools/osrm.py`, `overpass.py`, `wikimedia.py`, `open_meteo.py`) yra
  paprasti CLI scenarijai (`argparse` + `__main__`), kuriuos agentas kviečia per Claude
  Code įmontuotą **Bash** įrankį — ne per Python-side tool-registration API.
  `tools/github.py` — išimtis, kviečiamas tiesiogiai iš `agents/cicd.py` (deterministinis
  GitHub API darbas, ne LLM sprendimas).
- Strukūruotos išvestys (pvz. `TripRequirements`) per `claude -p --json-schema` + Pydantic
  validacija (`agents/requirements.py`) — pakeičia Anthropic Messages API
  `client.messages.parse()`, kuris nebeprieinamas be API rakto.
- Valdymo konsolė: FastAPI + HTMX + SQLite, skirta paleisti iš vienos vietos (žr. `console/`)
- `console/config.py` paleidimo metu tikrina `claude auth status --json` (ne API raktą)

## Darbo eiga

Kiekvienas komponentas (žr. GitHub Issues) implementuojamas atskiroje `claude/*` šakoje ir
pateikiamas kaip atskiras PR. `.github/workflows/auto-merge.yml` automatiškai sujungia
`claude/*` šakų PR į `main` (squash).

## Testavimas

Kiekvienas `tools/*.py` modulis turėtų turėti paprastą smoke testą (tiesioginis HTTP
kvietimas realiam API, ne mock) — šie API yra nemokami ir be rate limit problemų testavimo
apimtimi.

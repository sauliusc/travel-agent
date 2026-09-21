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

- **Python 3.10+**, `anthropic` SDK 1.x, `client.beta.messages.tool_runner()` su `@beta_tool`
- Modelis: `claude-opus-5`, `thinking: {"type": "adaptive"}`
- Nemokami išoriniai API: OSRM (važiavimo laikai), Overpass (kelio tipas), Wikimedia Commons
  (nuotraukos), Open-Meteo (oras); Anthropic `web_search`/`web_fetch` server tools tyrimui
- Strukūruotos agentų tarpusavio išvestys per Pydantic + `output_config.format`
- Valdymo konsolė: FastAPI + HTMX + SQLite, skirta paleisti iš vienos vietos (žr. `console/`)

## Darbo eiga

Kiekvienas komponentas (žr. GitHub Issues) implementuojamas atskiroje `claude/*` šakoje ir
pateikiamas kaip atskiras PR. `.github/workflows/auto-merge.yml` automatiškai sujungia
`claude/*` šakų PR į `main` (squash).

## Testavimas

Kiekvienas `tools/*.py` modulis turėtų turėti paprastą smoke testą (tiesioginis HTTP
kvietimas realiam API, ne mock) — šie API yra nemokami ir be rate limit problemų testavimo
apimtimi.

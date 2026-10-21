# Kelionių planavimo agentinė sistema — architektūra

Dokumentas aprašo **dabartinę** sistemą taip, kaip ji įgyvendinta šioje repozitorijoje.
Pradinis dizainas (Anthropic SDK, Tool Runner, Map ir Documentation agentai) yra
[dizaino dokumente](https://claude.ai/code/artifact/147e64cc-db43-43dd-a08c-263438c75677) —
jis paliktas istorijai; kur jis skiriasi nuo šio dokumento, galioja šis.

Atnaujinant agentą (jo įvestį, užklausą ar įrankius), atnaujinkite ir atitinkamą šio
dokumento skyrių.

## 1. Apžvalga

Vartotojas valdymo konsolėje (FastAPI + HTMX, `console/`) įklijuoja kelionės reikalavimus
laisvu tekstu. `orchestrator.py` paleidžia žingsnių grandinę: dalis žingsnių yra **AI
agentai** (`claude -p` kvietimai), dalis — **deterministinis kodas** (orų prognozė,
žemėlapis, nuotraukų atsisiuntimas, Booking.com skaitymas, publikavimas). Rezultatas —
vieno failo HTML kelionės puslapis, publikuojamas atskiroje GitHub repozitorijoje per
GitHub Pages.

Pagrindiniai principai:

- **Logistika tikrinama kodu ir agentu prieš puslapį.** Maršrutas be patvirtintų kelių
  (SH74 atvejis) puslapio nepasiekia (`validate_until_ok`, `LogisticsBlocked`).
- **Struktūruotos išvestys.** Dauguma agentų grąžina JSON pagal Pydantic schemą
  (`--json-schema`), kurią kodas validuoja; laisvu tekstu atsako tik Research, Weather,
  Accommodation (pirminis), Budget ir Page Designer (HTML).
- **Ką gali padaryti kodas, daro kodas:** žemėlapis, daiktų sąrašo checkbox'ai, orai,
  nuotraukų licencijos, Booking.com duomenys, puslapio patikros — ne LLM.
- **Pakartotinis panaudojimas.** Kiekvieno žingsnio išvestis saugoma (`trip_stages`), o
  perleidžiant žingsnis vykdomas iš naujo tik pasikeitus jo įvesčiai (pirštų atspaudas).

## 2. Kaip iškviečiamas agentas

Visi agentai kviečiami per `agents/base.py` → `_invoke_claude()`:

```
echo "<užklausa>" | claude -p \
  --append-system-prompt "<prompts/<agentas>.md turinys>" \
  --allowedTools <leidžiami įrankiai> \
  --disallowedTools Write,Edit,NotebookEdit[,<papildomai uždrausti>] \
  --permission-mode auto \
  --output-format json \
  --session-id <uuid> \
  [--json-schema <Pydantic schema>]
```

- **Užklausa** perduodama per stdin, ne kaip argumentas — Linux riboja vieną argumentą
  128 KB (`Argument list too long`).
- **Modelis:** `--model` nenurodomas — naudojamas Claude Code CLI numatytasis modelis
  (prenumeratos `claude auth login`). Kuris modelis realiai atsakė, įrašoma iš
  `modelUsage` ir matoma konsolėje: ⚙️ → Agentai.
- **Sistemos promptas** = atitinkamas `prompts/*.md` failas (kai kur su priedu, žr. žemiau).
- **Užklausa** (`-p`) = agento kontekstas, suformuotas kode pagal šablonus žemiau.
- **Failų rašymas visada uždraustas** (`ALWAYS_DISALLOWED`): agento rezultatas yra tik jo
  atsakymas.
- **Įrankiai:** Claude Code įmontuoti `WebSearch`, `WebFetch`, `Bash`. Projekto įrankiai
  (`tools/*.py`) agentams prieinami per `Bash` kaip CLI scenarijai.
- **Žurnalas:** kiekvienas kvietimas (pilna užklausa, atsakymas, modelis, įrankiai,
  trukmė) įrašomas į `trip_agent_calls` ir rodomas konsolėje.
- **Struktūruotas atsakymas:** `run_structured()` prideda `--json-schema` ir validuoja
  `structured_output` pagal Pydantic modelį.

### 2.1 Išoriniai AI tiekėjai (Gemini, OpenAI-suderinami)

Konsolėje (⚙️ Nustatymai → **AI tiekėjai**) galima pridėti API galinius taškus su raktais
(`ai_providers` lentelė) ir kiekvienam agentui pasirinkti, kuo jis vykdomas (⚙️ → Agentai →
„AI vykdymas“; `agent_providers`). `_invoke_claude()` pagal einamą žingsnį (`log_calls`)
nukreipia kvietimą į `agents/providers.py`, kuris grąžina tokios pat formos atsakymą kaip
`claude -p` — agentų kodas nesikeičia.

- Tas pats sistemos promptas ir užklausa; struktūruotai išvesčiai prie užklausos pridedama
  JSON schema, atsakymas validuojamas ta pačia Pydantic schema.
- `WebSearch`/`WebFetch` → Gemini `google_search` / `url_context`; OpenAI-suderinami
  tiekėjai web įrankių negauna.
- Agentai, kurie per `Bash` naudoja projekto įrankius (Logistika, Nuotraukos, Oras/sezonas,
  Maistas, Planas B — `BASH_AGENTS`), visada vykdomi Native Claude.
- Raktai saugomi `console.db` ir per API negrąžinami (rodomos tik 4 paskutinės raidės).
- **Agentų rinkiniai** (`agent_profiles`, `agent_profile_providers`): pavadinti tiekėjų
  pasirinkimų rinkiniai. „Base“ (id 1) — pradinė konfigūracija, nekeičiama; ją galima
  nukopijuoti nauju pavadinimu ir keisti kopiją. Kelionė kuriama su pasirinktu rinkiniu
  (`trips.profile_id`); visi jos paleidimai (perleidimas, pataisymai, bandymas iš naujo)
  naudoja tą rinkinį (`providers.using_profile`).

## 3. Žingsniai ir priklausomybės

Eiliškumas — `STAGE_ORDER`, priklausomybės — `STAGE_DEPS` (`orchestrator.py`).

| Žingsnis | Tipas | Priklauso nuo | Išvestis |
| --- | --- | --- | --- |
| `requirements` | agentas | — | `TripRequirements` JSON |
| `research` | agentas | requirements | tekstas |
| `weather` | agentas | requirements | tekstas |
| `accommodation` | agentas | requirements, research | tekstas (nakvynės planas) |
| `stay` | kodas | accommodation | Booking.com detalės + nuotraukos |
| `itinerary` | agentas | requirements, research, weather, accommodation | `Itinerary` JSON |
| `logistics_report` | agentas (+kodas) | itinerary | `LogisticsReport` JSON |
| `map_data` | kodas | itinerary | taškai + maršrutai |
| `images` | agentas + kodas | itinerary | `ImageResults` (patikrintos nuotraukos) |
| `car_rental` | agentas | requirements | `CarRentalResults` |
| `food` | agentas | requirements, itinerary, accommodation | `FoodGuide` |
| `forecast` | kodas | requirements, itinerary | `TripForecast` |
| `plan_b` | agentas + kodas | requirements, itinerary | `PlanBChecked` |
| `packing` | agentas | requirements, itinerary, forecast, car_rental | `PackingList` |
| `budget` | agentas | itinerary, accommodation, car_rental, food | tekstas |
| `page` | agentas + Critic | beveik visi | HTML |
| `deploy_log` | kodas | page, images, food | publikavimo žurnalas |

## 4. Agentai: kontekstas ir užklausa

Kiekvienam agentui nurodyta: **kontekstas** (kokie duomenys paduodami), **užklausa**
(tikslus `-p` tekstas, kai kontekstas įstatytas — `{...}` žymi įstatomą reikšmę),
**įrankiai**, **išvestis** ir **kodo patikros**.

### 4.1 Requirements Analyst — `agents/requirements.py`

- **Sistemos promptas:** `prompts/requirements.md`
- **Kontekstas:** vartotojo laisvas tekstas, be pakeitimų.
- **Užklausa:**
  ```
  {vartotojo įklijuotas kelionės aprašymas}
  ```
- **Įrankiai:** jokių. **Schema:** `TripRequirements` (destination, trip_type,
  start/end_date, travelers, budget_eur, airport, return_flight_time,
  transport (`car` | `public_transport`), max_driving_hours_per_day, priorities, language,
  notes). **Limitas:** 300 s.

### 4.2 Research — `agents/research.py`

- **Sistemos promptas:** `prompts/research.md`
- **Kontekstas:** `TripRequirements` JSON.
- **Užklausa:**
  ```
  {requirements JSON}
  ```
- **Įrankiai:** `WebSearch`, `WebFetch`. **Išvestis:** laisvas tekstas: objektai su darbo
  laiku ir bilietų kainomis, renginiai kelionės datomis, keliai, sezoniškumas, praktinė
  informacija (dokumentai, pinigai, papročiai, saugumas, pagalbos numeris, transportas), šaltiniai.

### 4.3 Weather/Season — `agents/weather.py`

- **Sistemos promptas:** `prompts/weather.md`
- **Kontekstas:** `TripRequirements` JSON + įrankio nuoroda.
- **Užklausa:**
  ```
  {requirements JSON}

  Use Bash to check typical conditions: `python3 tools/open_meteo.py --lat .. --lon .. --month <1-12>`.
  Use WebSearch for anything not covered by that (e.g. seasonal road closures).
  ```
- **Įrankiai:** `Bash`, `WebSearch`. **Išvestis:** tekstas (sezoninis tinkamumas).

### 4.4 Accommodation — `agents/accommodation.py`

Du režimai.

**a) Pirminė paieška (`find`)**

- **Sistemos promptas:** `prompts/accommodation.md`
- **Kontekstas:** requirements JSON, Research tekstas; jei pradiniame tekste yra
  Booking.com nuoroda — kodo perskaitytos jos detalės (`tools/booking.py`).
- **Užklausa:**
  ```
  requirements={requirements JSON}
  research={research tekstas}
  booked_property (read from the traveller's booking.com link; keep this place and its link)={detalių JSON}   ← tik jei yra nuoroda
  ```
- **Įrankiai:** `WebSearch`. **Išvestis:** tekstas — 2–3 variantai kiekvienam nakvynės
  miestui su kaina ir nuoroda.

**b) Pataisymas (`update`, kai vartotojas spaudžia „Pataisyti“)**

- **Sistemos promptas:** `prompts/accommodation.md` + `UPDATE_RULES` (pakeitimas taikomas
  tik nakvynei; vartotojo nurodyta vieta pakeičia seną; Booking.com nuoroda išlaikoma
  pažodžiui).
- **Kontekstas:** requirements JSON, esamas nakvynės planas, pataisymo tekstas, kodo
  perskaitytos Booking.com detalės iš pataisymo.
- **Užklausa:**
  ```
  Trip requirements:
  {requirements JSON}

  Current accommodation plan:
  {esamas planas}

  Change request:
  {vartotojo pataisymas}

  Booking.com page(s) from the request, already read for you (don't fetch them):
  {detalių JSON}   ← tik jei yra nuoroda
  ```
- **Įrankiai:** `WebSearch`, `WebFetch`. **Schema:** `AccommodationUpdate {changed,
  accommodation}`. **Limitas:** 900 s.

### 4.5 Itinerary Planner — `agents/itinerary.py`

**a) Pirminis planas (`plan`)**

- **Sistemos promptas:** `prompts/itinerary.md`
- **Kontekstas:** requirements, research, weather, accommodation.
- **Užklausa:**
  ```
  requirements={requirements JSON}
  research={research}
  weather={weather}
  accommodation={nakvynės planas}

  Finish all checks within this turn and return the complete final itinerary. Do not start
  background jobs or promise to report results later -- there is no later turn.
  ```

Kiekviena stotelė turi `maps_query` (pavadinimas + miestas + šalis; dviprasmiško pavadinimo
atveju — gatvės adresas; tuščia — koordinatės). `google_maps_url` užpildo kodas
(`tools/maps_links.py` → `with_place_urls`), ne agentas.

**b) Taisymas (`fix`)** — kviečiamas po vartotojo pataisymo, logistikos blokatorių ar
Critic radinių (`target: itinerary`).

- **Kontekstas:** esamas planas + problemų sąrašas.
- **Užklausa:**
  ```
  Current itinerary:
  {Itinerary JSON}

  Issues to fix:
  {problemos}

  Change only what the issues/request require. Copy every other day exactly as it is in the
  current itinerary -- same stops, times, notes, wording. List in `changed_days` every day
  you changed, including knock-on changes; days not listed are restored from the current
  itinerary automatically.

  Finish all checks within this turn ...
  ```
  `{problemos}` pagal šaltinį:
  - vartotojo pataisymas: `{pataisymas}` + `Current accommodation (updated -- it replaces any
    place to stay named in the original request; every stop at the old lodging ... must move
    to the new one with its coordinates): {nakvynės planas}`;
  - logistika: `Logistics Validator blockers:` + `- {kur}: {problema} -> {sprendimas}`;
  - Critic: `- [itinerary/blocker] {kur}: {problema} -> {sprendimas}`.
- **Įrankiai:** jokių (`Bash`, `WebSearch`, `WebFetch` uždrausti — tikrina Logistika).
  **Schema:** `Itinerary` / `ItineraryFix {itinerary, changed_days, change_summary}`.
  **Kodas:** nepažymėtos dienos atkuriamos iš ankstesnio plano. **Limitas:** 1200 s.

### 4.6 Logistics Validator — `agents/logistics.py`

- **Sistemos promptas:** `prompts/logistics.md`
- **Kontekstas:** Itinerary JSON, įrankio nuoroda; pakartotinai — ankstesnė ataskaita
  (patvirtintos atkarpos pernaudojamos).
- **Užklausa:**
  ```
  {Itinerary JSON}

  Check each leg with ONE call: `python3 tools/route_check.py --from-lat .. --from-lon ..
  --to-lat .. --to-lon ..` -- it returns real distance/time and the road type at points sampled
  along the actual route, ending in `LEG OK`, `LEG WARNING` (not paved/drivable) or `LEG UNKNOWN`
  (road data service unreachable -- not a road problem; retry that leg once, then research it as
  unconfirmed). Run legs one after another, not in parallel ... `python3 tools/overpass.py
  --lat .. --lon ..` is only for spot-checking one specific point.
  Each stop's `arrive_by` says how the travellers get there ... 'walk' legs: `route_check.py
  --mode walk`; 'transit' legs: confirm the line with web search, door-to-door time and ticket.

  This trip has NO car: ... no driving tips.   ← tik kai transport = public_transport

  Previous validation report for an earlier version of this itinerary is below. For a leg with
  the same from/to stops as a leg confirmed there, reuse that result ... check only new or
  changed legs. Daily totals and the airport buffer must still be recomputed for the current plan.
  {ankstesnė LogisticsReport JSON}   ← tik pakartotinai
  ```
- **Įrankiai:** `Bash` (`tools/route_check.py` = OSRM + Overpass, `tools/overpass.py`),
  `WebSearch`, `WebFetch`. **Schema:** `LogisticsReport` (atkarpos, blokatoriai,
  `traveler_tips`). **Limitas:** 1200 s.
- **Kodas:** `enforce_modes` — atkarpos perstatomos plano tvarka su plano transporto rūšimi
  (`Stop.arrive_by`: `car` / `walk` / `transit`): ėjimo laikas visada perskaičiuojamas
  (`route_check.walk_check`, FOSSGIS foot OSRM; nepasiekus — tiesės atstumas ×1,3, 4,5 km/h),
  ėjimas > 5 km, automobilis kelionėje be automobilio, transportas be linijos ir kitu būdu
  patikrinta atkarpa — blokatoriai; dienos vairavimo limitas tikrinamas tik automobilio
  atkarpoms. Puslapiui kiekviena atkarpa gauna `icon` (🚗/🚶/🚇/🚌/🚋/🚆...).
- **Kodas:** `validate_until_ok` — esant blokatoriams iki 2 kartų kviečia Itinerary `fix`
  ir tikrina iš naujo; nepavykus — `LogisticsBlocked` (puslapis nekuriamas).

### 4.7 Image — `agents/images.py`

- **Sistemos promptas:** `prompts/images.md`
- **Kontekstas:** Itinerary, sumažintas iki sustojimų, kuriems dar nėra nuotraukos.
- **Užklausa:**
  ```
  {Itinerary JSON (tik be nuotraukų likę sustojimai)}

  Use Bash to look up each stop: `python3 tools/wikimedia.py --query "<place name>"`.
  ```
- **Įrankiai:** `Bash`. **Schema:** `ImageResults`. **Limitas:** 300 s.
- **Kodas:** `tools/image_download.py` iš Commons patikrina licenciją ir autorių (ne iš
  agento žodžių), atsisiunčia ir patikrina failą; netinkamos atmetamos.

### 4.8 Car Rental — `agents/car_rental.py`

- **Sistemos promptas:** `prompts/car_rental.md`
- **Kontekstas:** requirements JSON + originalus vartotojo tekstas.
- **Užklausa:**
  ```
  Trip requirements:
  {requirements JSON}

  Original request:
  {vartotojo tekstas}
  ```
- **Įrankiai:** `WebSearch`, `WebFetch`. **Schema:** `CarRentalResults` (needed, car types
  + kainos, 3 įmonės). **Kodas:** kai `transport` ≠ `car`, agentas nekviečiamas
  (`needed: false`); tikrina, kad 3 įmonės turi pakankamą įvertinimą ir
  atsiliepimų skaičių. **Limitas:** 900 s.

### 4.9 Food & Bars — `agents/food.py`

- **Sistemos promptas:** `prompts/food.md`
- **Kontekstas:** requirements, itinerary, nakvynės planas.
- **Užklausa:**
  ```
  Trip requirements:
  {requirements JSON}

  Itinerary:
  {Itinerary JSON}

  Accommodation:
  {nakvynės planas}
  ```
- **Įrankiai:** `WebSearch`, `WebFetch`, `Bash` (patiekalų nuotraukos per Wikimedia).
  **Schema:** `FoodGuideDraft`. **Kodas:** prideda Google Maps nuorodas (pavadinimas + `address`, jei
  žinomas, kitaip miestas) ir patikrintas
  patiekalų nuotraukas (→ `FoodGuide`) — regioninių patiekalų ir kiekvienos užeigos `must_try`
  (≥ 3 patiekalai su kaina; schema reikalauja `minItems: 3`), kiekvienas Commons failas
  atsisiunčiamas vieną kartą; `must_try` be savo nuotraukos pasiima to paties regioninio
  patiekalo nuotrauką. Užeiga turi ir `dinner_price_eur` (preliminari vakarienė asmeniui). **Limitas:** 1200 s.

### 4.10 Plan B — `agents/plan_b.py`

- **Sistemos promptas:** `prompts/plan_b.md`
- **Kontekstas:** requirements, pagrindinis planas, orų prognozė.
- **Užklausa:**
  ```
  Trip requirements:
  {requirements JSON}

  Itinerary (main plan):
  {Itinerary JSON}

  Weather for the trip dates:
  {TripForecast JSON}
  ```
  Jei kodo patikra randa problemų — vienas pakartojimas:
  ```
  {ta pati užklausa}

  Your previous Plan B:
  {PlanB JSON}

  It has these problems -- fix them and return the complete Plan B:
  - {problema}
  ```
- **Įrankiai:** `WebSearch`, `WebFetch`, `Bash`. **Schema:** `PlanB`. **Limitas:** 1200 s.
- **Kodas:** ta pati pradžia ir pabaiga kaip pagrindinio plano dieną, automobilio keliai per
  `route_check` (asfaltuoti), vairavimo limitas; be automobilio — jokių `car` atkarpų, ėjimas
  ≤ 5 km, transportui — nurodyta linija; maršruto nuorodos su `route_modes`; kelių tarnybos sutrikimas fiksuojamas kaip
  „nepatikrinta“, ne kaip klaida.

### 4.11 Packing Planner — `agents/packing.py`

- **Sistemos promptas:** `prompts/packing.md`
- **Kontekstas:** requirements, originalus tekstas, itinerary, prognozė, ar nuomojamas
  automobilis.
- **Užklausa:**
  ```
  Trip requirements:
  {requirements JSON}

  Original request:
  {vartotojo tekstas}

  Itinerary:
  {Itinerary JSON}

  Forecast:
  {TripForecast JSON}

  Rental car: {true|false}
  ```
- **Įrankiai:** jokių (`Bash`, `WebSearch`, `WebFetch` uždrausti). **Schema:** `PackingList`.
  **Kodas:** checkbox'ai su `localStorage` generuojami `tools/packing_html.py` ir įterpiami
  vietoje `<!-- PACKING_LIST -->`. **Limitas:** 600 s.

### 4.12 Budget — `agents/budget.py`

- **Sistemos promptas:** `prompts/budget.md`
- **Kontekstas:** itinerary, nakvynės planas, automobilio nuoma, maisto gidas (be nuotraukų).
- **Užklausa:**
  ```
  {"itinerary": ..., "accommodation": ..., "car_rental": {...}, "food": {...}}
  ```
- **Įrankiai:** `WebSearch`. **Išvestis:** tekstas (biudžeto lentelė).

### 4.13 Page Designer — `agents/page_designer.py`

- **Sistemos promptas:** `prompts/page_designer.md`
- **Kontekstas** (`page_context()`): `language`, `research` (praktinė informacija ir renginiai), `accommodation`, `stays` (Booking.com
  detalės ir nuotraukos), `itinerary`, `day_routes` (Google Maps dienos maršrutų URL),
  `logistics` (atkarpos be vidinių įrodymų + `traveler_tips`), `budget`, `images`,
  `car_rental`, `food`, `forecast`, `plan_b`, `nearby` (užeigos ir parduotuvės prie
  nakvynių); `map_data` ir `packing` — tik nuoroda, kad
  vietą užima kodas (`<!-- TRIP_MAP -->`, `<!-- PACKING_LIST -->`).
- **Užklausa — naujas puslapis (`design`):**
  ```
  {page_context JSON}

  Reply with the complete HTML document itself as your entire answer, starting with
  <!DOCTYPE html>. Do not write files, and do not describe or summarise what you did.
  ```
- **Užklausa — atnaujinimas (`update`, numatytasis perleidžiant):**
  ```
  You are updating an already published trip page, not designing a new one. Below are the
  current page and the current data. Apply the listed changes and make every part of the page
  match the current data, but keep the design -- colors, layout, CSS, JS, section order -- and
  all wording that isn't affected exactly as it is. Keep the <!-- PACKING_LIST --> and
  <!-- TRIP_MAP --> lines where they are.

  Changes:
  {pakeitimų sąrašas: vartotojo prašymas, plano santrauka, Critic radiniai}
  Updated data: {pasikeitusių žingsnių pavadinimai}

  Current data:
  {page_context JSON}

  Current page:
  {ankstesnis HTML, kodo blokai pakeisti į žymes}

  Reply with the complete HTML document itself ...
  ```
- **Įrankiai:** jokių (`Bash`, `Read`, `Glob`, `Grep`, `WebSearch`, `WebFetch` uždrausti).
  **Kodas:** `extract_html` atmeta ne-HTML atsakymą; žemėlapis (`tools/map_html.py`) ir
  daiktų sąrašas įterpiami kodu. **Limitas:** 900 s.

### 4.14 Review/Critic — `agents/critic.py`

- **Sistemos promptas:** `prompts/critic.md` (10 patikrų: logistikos atitikimas,
  vairavimo limitas, oro uosto rezervas, koordinatės, nuotraukos, Maps nuorodos, kalba
  keliautojui, maistas/nuoma, orai/daiktai, Planas B).
- **Kontekstas:** puslapio HTML, itinerary, logistikos ataskaita, nuotraukų manifestas,
  dienų maršrutų URL, jau taisytų radinių sąrašas.
- **Užklausa:**
  ```
  Page HTML:
  {HTML}

  Itinerary:
  {Itinerary JSON}

  Logistics report (already passed validation):
  {LogisticsReport JSON}

  Verified image manifest:
  {ImageResults JSON}

  Day route links (day_routes):
  {day_routes JSON}

  Already fixed in an earlier round -- check they are resolved, do not re-report them unless
  still wrong:
  {ankstesni radiniai}   ← nuo 2-o rato
  ```
- **Įrankiai:** jokių. **Schema:** `Review {issues: [{target: page|itinerary, severity:
  blocker|minor, where, problem, fix}]}`.
- **Ciklas (iki 3 ratų):**
  1. `tools/page_checks.py` (kodas, nemokamai): nuotraukų keliai ∈ manifestas, dienų
     maršrutų URL, kiekvienos stotelės / užeigos / baro / vietos prie nakvynės Google Maps
     nuoroda, kiekvienas užeigos `must_try` patiekalas,
     `PACKING_LIST`/`TRIP_MAP` žymės, ranka rašyto žemėlapio nebuvimas,
     kiekvienas `traveler_tips` puslapyje. Radus — taisomas tik puslapis.
  2. Critic. Nėra `blocker` → baigta (`minor` naujo rato nekelia).
  3. `itinerary` blokatoriai → Itinerary `fix` → Logistika → puslapio atnaujinimas;
     tik `page` blokatoriai → tik puslapio atnaujinimas.

## 5. Kodo žingsniai (be LLM)

| Žingsnis / modulis | Ką daro |
| --- | --- |
| `stay` — `tools/booking.py` | Booking.com nuorodos iš nakvynės plano (iki 8): naršyklės užklausa, nepavykus — headless Chromium (Playwright); JSON-LD/OpenGraph → pavadinimas, adresas, įvertinimas, visas aprašymas, patogumai; iki 5 nuotraukų į `image_cache/`. |
| Booking.com paieška — `tools/booking_links.py` | Iš Nakvynės agento `picks` JSON bloko (miestas, vieta, datos, kaina) kiekvienai nakvynei sukuria Booking.com paieškos nuorodą su datomis ir žmonių skaičiumi (`booking_search` puslapio kontekste) ir patikrina kainos ribą (`max_price_per_night_eur`, vienas pakartojimas). |
| `map_data` — `tools/map_html.py` | Leaflet žemėlapis iš itinerary: taškai su tooltip (pavadinimas), popup (diena, laikas, Maps), dienų spalvos ir maršrutai. |
| `nearby` — `tools/nearby.py` | Prie kiekvienos nakvynės (paskutinė dienos stotelė, išskyrus paskutinę dieną; gretimos naktys toje pačioje vietoje sujungiamos): 5 artimiausios vietos pavalgyti ir 3 maisto parduotuvės iš OpenStreetMap (Overpass, 1 km, trūkstant — 3 km), atstumas (tiesė ×1,3) ir ėjimo laikas, Google Maps nuoroda. Nepavykus — tušti sąrašai su `error`. |
| Nuotraukų stilius — `tools/photo_style.py` | Fiksuotas CSS (`spot-thumb` didelė per visą kortelę, `photo-grid`, `dish-grid` + `dish-thumb`) įterpiamas į `<head>` po kiekvieno puslapio generavimo, kad nuotraukų dydis nesikeistų tarp iteracijų. |
| `forecast` — `tools/forecast.py` | Open-Meteo prognozė iki 16 d.; toliau arba be duomenų — 5 metų klimato vidurkis. |
| nuotraukos — `tools/image_download.py` | Commons licencijų ir autorių patikra, atsisiuntimas. |
| `day_routes` — `tools/maps_links.py` | Google Maps dienos maršruto URL, po vieną kiekvienai tos pačios transporto rūšies atkarpų sekai (`modes`: automobiliu / pėsčiomis / viešuoju transportu — transitas be tarpinių taškų, todėl kiekviena tokia atkarpa atskirai) — vietos pavadinimais (`maps_query`: pavadinimas + miestas, dviprasmiškai — adresas), be jo — koordinatės. Taip pat kiekvienos stotelės, užeigos ir baro Google Maps nuoroda. |
| `deploy_log` — `agents/cicd.py` + `tools/github.py` | Repozitorija `ai-trip-*`, `index.html` + nuotraukos, GitHub Pages. |

## 6. Pakartotinis paleidimas ir pataisymai

- **Pirštų atspaudas:** `sha256(žingsnis + prompt failai + priklausomybių išvestys)`
  (`_fp:<žingsnis>`). Perleidžiant nuo žingsnio X: X vykdomas visada, vėlesni — tik
  pasikeitus atspaudui. Kodo žingsniai (`CODE_STAGES`), kurių senoje kelionėje nėra,
  apskaičiuojami vietoje.
- **„Pataisyti“:** pradedama nuo `accommodation` su pataisymo tekstu → Accommodation
  `update` → Itinerary `fix` → toliau pagal atspaudus; puslapis atnaujinamas, ne kuriamas iš
  naujo.
- **„Bandyti dar kartą“:** tęsia **tą pačią** kelionę nuo žingsnio po paskutinio baigto
  (`_resume`); nepritaikytas pataisymas pritaikomas iš naujo, jau pritaikytas perduodamas
  puslapio atnaujinimui.
- **„↻ Puslapis“:** puslapis kuriamas iš naujo (naujas dizainas).

### Užklausų istorija kelionės repozitorijoje

Kiekvienas paleidimas (pradinė užklausa, pataisymas, perleidimas nuo žingsnio, bandymas iš
naujo) kelionės repozitorijoje sukuria `request-history/<data>_<tipas>.md`
(`tools/run_history.py`): laikas, agentų rinkinys, rezultatas, eiga ir kiekvienas agento
kvietimas — modelis, vykdytojas, trukmė, užklausa ir atsakymas skaitomu formatu (JSON
gražiai suformatuotas, HTML puslapis pakeistas užrašu „HTML puslapis sugeneruotas“).
Jei pirmas paleidimas nepavyko iki repozitorijos sukūrimo, istorija neišsaugoma.

## 7. Valdymo konsolė

- `console/app.py` (FastAPI), `console/db.py` (SQLite: `trips`, `trip_events`,
  `trip_stages`, `trip_agent_calls`), `console/static/index.html` (kelionės),
  `console/static/settings.html` (⚙️ Nustatymai → Agentai: modelis, įrankiai, promptas ir
  paskutinės užduotys kiekvienam agentui).
- Diegimas: Proxmox LXC (CT110), `systemd` servisas `travel-console`; atnaujinimas —
  `cd /opt/travel-agent && bash scripts/update.sh`.

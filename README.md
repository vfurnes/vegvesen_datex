# Statens vegvesen DATEX — Home Assistant

Kobler Home Assistant mot **Statens vegvesen sine DATEX II (v3.x) data** og gir deg:

- 🌦 **Vegværstasjoner** — temperatur, vind, luftfuktighet, føreforhold
- 🚧 **Trafikkhendelser innenfor en radius** fra et valgt punkt, f.eks. 20 km hjemmefra
- 🗺 **Kartmarkører** som dukker opp og forsvinner med hendelsene
- 📋 **Ferdig formatert hendelsestekst** til dashbord og varsler

Integrasjonen er utviklet i tett samarbeid med ChatGPT — både kode og dokumentasjon 😊

---

## 🔑 Krav

- **Home Assistant 2025.3.0** eller nyere
- **Tilgang til Statens vegvesen sitt DATEX-API** — brukernavn og passord, bestilles hos Statens vegvesen

Offisiell DATEX-dokumentasjon:
<https://git.vegvesen.no/projects/DATEX2/repos/datex2-spesifications/browse/3.1>

---

## 📦 Installasjon

### HACS (anbefalt)

1. HACS → ⋮ → **Egendefinerte repositorier**
2. Legg til `https://github.com/vfurnes/vegvesen_datex`, kategori **Integration**
3. Installer **Statens vegvesen DATEX**
4. Start Home Assistant på nytt

### Manuelt

Kopier `custom_components/vegvesen_datex` til `/config/custom_components/` og start om.

Legg deretter til integrasjonen under **Innstillinger → Enheter og tjenester → Legg til
integrasjon**. Du oppgir DATEX-brukernavn og passord, og kan så legge til så mange
værstasjoner og radiusområder du vil.

---

## ✨ Hva du får

### 🌦 Værstasjoner

For hver valgte målestasjon opprettes de sensorene stasjonen faktisk leverer:

| Sensor | Enhet | `device_class` | `state_class` |
|---|---|---|---|
| Temperatur | °C | `temperature` | `measurement` |
| Luftfuktighet | % | `humidity` | `measurement` |
| Vindstyrke | m/s | `wind_speed` | `measurement` |
| Vindkast | m/s | `wind_speed` | `measurement` |
| Vindretning | ° | `wind_direction` | — |
| Nedbørsintensitet | mm/h | `precipitation_intensity` | `measurement` |
| Vegbanetemperatur | °C | `temperature` | `measurement` |
| Føreforhold | — | — | — |
| Friksjon, vannfilm, islag, snødybde | m | — | `measurement` |

Alle måleverdier havner i langtidsstatistikk. Vindretning får bevisst ingen
`state_class`, siden Home Assistant ikke tillater det for retningsangivelser.

Hver sensor har attributtet `sist_oppdatert` med måletidspunktet fra DATEX.
Vindkast har i tillegg `periode_start` og `periode_slutt`.

> **Merk:** ikke alle stasjoner leverer alt. Rv 15 Måløybrua publiserer for eksempel
> temperatur, luftfuktighet og **vindkast**, men verken vindstyrke eller vindretning.
> Sensorer for målinger stasjonen ikke sender vil stå som `unknown`. Det er ikke en
> feil i integrasjonen — sjekk hva stasjonen faktisk viser på vegvesen.no.

### 🚧 Trafikkhendelser innenfor radius

Velg en Home Assistant-sone som midtpunkt og en radius i km. Du får:

| Entitet | Tilstand | Nyttige attributter |
|---|---|---|
| `sensor.<navn>_status` | antall hendelser | `matched`, `radius_km`, `zone`, `center` |
| `sensor.<navn>_hendelse` | `"3 hendelser"` | `matched`, `message` (strukturert liste) |
| `binary_sensor.<navn>_stengt` | `on` hvis en vei er stengt | |
| `geo_location.*` | avstand i km | se under |

### 🗺 Kartmarkører

Det opprettes **én markør per hendelse** — ingen faste plasser, ingen øvre grense.
Markøren fjernes helt når hendelsen er over, og oppføringen slettes fra
entitetsregisteret, så det samler seg ikke opp gamle entiteter.

Hendelser som deler vei og nøyaktig posisjon slås sammen til én markør. DATEX
publiserer ofte flere meldinger for samme fysiske veiarbeid — «Vedlikeholdsarbeid»
og «Vei-/feltregulering» på samme punkt — og uten sammenslåing ville de blitt
liggende oppå hverandre på kartet.

Attributter per markør:

| Attributt | Beskrivelse |
|---|---|
| `event_text` | ferdig visningstekst: `F614 – Hornelsvegen \| Vedlikeholdsarbeid (17.47 km)` |
| `road`, `road_number`, `road_name` | veien hendelsen gjelder |
| `what`, `what_list` | hendelsestype(r) |
| `closed` | `true` hvis veien er stengt |
| `event_count` | antall DATEX-meldinger slått sammen i markøren |
| `distance_km` | avstand fra midtpunktet |
| `start_time`, `expected_end_time`, `last_update` | tidspunkter fra DATEX |

---

## 🗺 Dashbord-eksempler

### Kart

Kartet henter markørene selv — du slipper å ramse opp entiteter:

```yaml
type: map
title: Hendelser (20 km)
geo_location_sources:
  - vegvesen_datex
```

### Liste over hendelser

Stengte veier først, deretter nærmest først:

```yaml
type: markdown
content: >
  {% set entities = states.geo_location
    | selectattr('attributes.source', 'eq', 'vegvesen_datex')
    | selectattr('attributes.distance_km', 'defined')
    | sort(attribute='attributes.distance_km')
    | sort(attribute='attributes.closed', reverse=true)
    | map(attribute='entity_id') | list %}
  {% if entities | count == 0 %}
    Ingen aktive hendelser
  {% else %}
    {% for e in entities %}
  {{ loop.index }}. {{ state_attr(e, 'event_text') }}
    {% endfor %}
  {% endif %}
```

Vil du bare vise de fem nærmeste, bytt `{% for e in entities %}` med
`{% for e in entities[:5] %}`.

### Vindvarsel for en bru

```yaml
type: custom:mushroom-template-card
primary: Måløybrua vindstatus
secondary: >
  {% set gust = states('sensor.rv_15_maloybrua_vindkast') | float(0) %}
  {% if gust >= 28 %}Fare for stengt bro
  {% elif gust >= 20 %}Kraftig vind
  {% elif gust >= 10 %}Moderat vind
  {% else %}Rolige forhold{% endif %} — {{ gust | round(1) }} m/s
icon: mdi:weather-windy
```

Krever [Mushroom](https://github.com/piitaya/lovelace-mushroom). Kart- og
markdown-eksemplene over bruker bare innebygde kort.

---

## ⚠️ Oppgradering til 0.3.0

Hendelser var tidligere `device_tracker`-entiteter. De er nå `geo_location`, som er
det Home Assistant faktisk har ment for kartmarkører — og som ga oss dynamiske
markører og ryddig opprydding på kjøpet.

**Dette er en bruddendring.** Etter oppgradering må du:

1. Bytte `entities:` med `geo_location_sources:` i kartkortene dine
2. Erstatte oppramsede `device_tracker.*`-ID-er i maler med filteret vist over
3. Slette de gamle `device_tracker`-entitetene under **Innstillinger → Enheter og
   tjenester → Entiteter** (filtrer på utilgjengelige)

Samtidig fikk værsensorene `state_class`, så de begynner å bygge langtidsstatistikk
fra og med oppgraderingen. Historikk fra før finnes ikke.

---

## 🚧 Videre planer

- Severity-mapping (lav / middels / høy)
- Filtrering per vegnummer
- Bedre klassifisering av hendelsestyper
- Dynamiske markører uten fast øvre grense — ✅ gjort i 0.3.0

---

## 🤝 Bidrag

Bidrag er svært velkomne — issues, pull requests, og særlig testere med DATEX-tilgang.

## 📄 Lisens

MIT

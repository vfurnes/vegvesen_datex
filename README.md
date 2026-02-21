# vegvesen_datex

Home Assistant -- Statens vegvesen DATEX II integration

Integrasjonen er utviklet i tett samarbeid med ChatGPT -- både kode og
dokumentasjon 😊

------------------------------------------------------------------------

# Statens vegvesen DATEX -- Home Assistant integration

Denne integrasjonen kobler Home Assistant mot **Statens vegvesen sine
DATEX II (v3.x) data** og gjør det mulig å vise:

-   🌦 Vegværstasjoner (temperatur, vind, luftfuktighet m.m.)
-   🚧 Trafikkhendelser innenfor valgt radius (f.eks. 20 km hjemmefra)
-   🗺 Kartmarkører for aktive hendelser
-   📋 Strukturert hendelsesliste klar for dashboard og automasjoner
-   ♻️ Automatisk opprydding når hendelser forsvinner

Integrasjonen er laget for privat bruk i Home Assistant, men kan også
brukes i andre ikke-kommersielle prosjekter.

------------------------------------------------------------------------

# ✨ Funksjoner

## 🌦 Værstasjoner (MeasuredDataPublication)

For hver valgt målestasjon opprettes sensorer for:

-   Temperatur (°C)
-   Luftfuktighet (%)
-   Vindstyrke (m/s)
-   Vindkast (m/s)
-   Vindretning (°)

Alle sensorer: - Har korrekt `device_class` - Bruker
`state_class: measurement` - Har native units - Inneholder metadata som
siste måletidspunkt

------------------------------------------------------------------------

## 🚧 Trafikkhendelser innen radius (SituationPublication)

Du kan konfigurere en radius (f.eks. 20 km fra hjemmeadresse).

For hver aktiv hendelse hentes:

-   Veistykke (f.eks. F616 -- Hornelsvegen)
-   Type hendelse (Accident, Roadworks, Maintenance, Closure, osv.)
-   Sist oppdatert tidspunkt
-   Starttid
-   Forventet sluttid (der tilgjengelig)
-   Koordinater (lat/lon)
-   Avstand fra valgt referansepunkt

------------------------------------------------------------------------

## 📋 Områdesensor (Area Summary Sensor)

Eksempel:

sensor.20km_hjemmefra_hendelse

State: 2 hendelser

Attributes: - matched - message (strukturert liste) - lines
(dashboard-klar tekst)

`lines` er ferdig formatert og egnet direkte til visning i dashboard
eller varsler.

------------------------------------------------------------------------

## 🗺 Kartmarkører (slot-basert modell)

For hvert radius-oppsett opprettes faste "slots":

geo_location.20km_hjemmefra_1\
geo_location.20km_hjemmefra_2\
...\
geo_location.20km_hjemmefra_10

Egenskaper:

-   Sortert nærmest først
-   Kun aktive hendelser fyller slots
-   Ubrukte slots blir `unavailable`
-   Ingen "ghost entities" når hendelser forsvinner

Dette gir stabil entity-ID og korrekt livssyklus.

------------------------------------------------------------------------

# 🔑 Krav

-   Home Assistant (nyeste versjon anbefalt)
-   Tilgang til Statens vegvesen DATEX API
    -   Krever brukernavn og passord
    -   Kan bestilles hos Statens vegvesen

Offisiell DATEX-dokumentasjon:\
https://git.vegvesen.no/projects/DATEX2/repos/datex2-spesifications/browse/3.1

------------------------------------------------------------------------

# 📦 Installasjon

## Manuell installasjon

1.  Last ned eller klon repoet
2.  Kopier:

custom_components/vegvesen_datex

til:

/config/custom_components/

3.  Start Home Assistant på nytt
4.  Legg til integrasjonen via:

Innstillinger → Enheter og tjenester → Legg til integrasjon

------------------------------------------------------------------------

# 🗺 Dashboard-eksempel

## Kart

``` yaml
type: map
title: Hendelser (20 km)
entities:
  - geo_location.20km_hjemmefra_1
  - geo_location.20km_hjemmefra_2
  - geo_location.20km_hjemmefra_3
```

## Liste (Mushroom)

``` yaml
type: custom:mushroom-template-card
primary: Hendelser innen 20 km
secondary: >
  {% set lines = state_attr('sensor.20km_hjemmefra_hendelse','lines') or [] %}
  {% if lines|length == 0 %}
    Ingen aktive hendelser
  {% else %}
    {% for l in lines %}
      {{ loop.index }}. {{ l }}
      {% if not loop.last %}{{ '\n' }}{% endif %}
    {% endfor %}
  {% endif %}
multiline_secondary: true
icon: mdi:map-marker-alert
```

------------------------------------------------------------------------

# 🚧 Status

Integrasjonen er i aktiv utvikling.

Planlagte forbedringer:

-   Severity-mapping (Low / Medium / High)
-   Spesialisert "Bro-overvåking"-modus (vindvarsler)
-   Filtrering per vegnummer
-   Forbedret klassifisering av hendelsestyper
-   HACS-ready release

------------------------------------------------------------------------

# 🤝 Bidrag

Bidrag er svært velkomne!

-   Issues for feil og forbedringer
-   Pull requests for nye funksjoner
-   Testere med DATEX-tilgang er spesielt verdifulle

------------------------------------------------------------------------

# 📄 Lisens

MIT License

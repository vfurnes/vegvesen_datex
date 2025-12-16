# vegvesen_datex
Home Assistant - Vegvesen Datex integration

Integrasjonen er laget i tett samarbeid med ChatGPT - det samme er readme..
---

# Statens vegvesen DATEX – Home Assistant integration

Denne integrasjonen kobler Home Assistant mot **Statens vegvesen sine DATEX II-data** og gjør det mulig å vise sanntidsstatus for vegobjekter som **bruer**, inkludert:

* 🟢 Åpen / 🔴 Stengt / ⚠️ Restriksjoner
* 🌬️ Vindrelaterte hendelser og (der tilgjengelig) vindstyrke
* 📢 Årsakstekst (f.eks. *stengt pga sterk vind*)

Integrasjonen er laget for privat bruk i Home Assistant, men kan også brukes i andre ikke-kommersielle prosjekter.

---

## ✨ Funksjoner

* Henter trafikkhendelser fra Vegvesen sitt **DATEX II API (v3.1)**
* Støtter **brukernavn og passord per Home Assistant-instans**
* Sensorer:

  * `binary_sensor` – vegobjekt stengt / ikke stengt
  * `sensor` – status (åpen / restriksjon / stengt)
  * `sensor` – hendelsestekst / årsak
  * `sensor` – vindinformasjon (der tilgjengelig)
* UI-basert oppsett via Home Assistant **Config Flow**
* Klar for distribusjon via **HACS**

---

## 🔑 Krav

* Home Assistant (nyeste versjon anbefalt)
* Tilgang til **Statens vegvesen DATEX API**

  * Krever brukernavn og passord
  * Kan bestilles hos Statens vegvesen

👉 Dokumentasjon for DATEX:
[https://git.vegvesen.no/projects/DATEX2/repos/datex2-spesifications/browse/3.1](https://git.vegvesen.no/projects/DATEX2/repos/datex2-spesifications/browse/3.1)

---

## 📦 Installasjon (utviklingsfase)

### Manuell installasjon

1. Last ned eller klon dette repoet
2. Kopier mappen:

   ```
   custom_components/vegvesen_datex
   ```

   til:

   ```
   /config/custom_components/
   ```
3. Start Home Assistant på nytt

> HACS-støtte kommer når integrasjonen er mer moden.

---

## ⚙️ Konfigurasjon

1. Gå til **Innstillinger → Enheter og tjenester**
2. Klikk **Legg til integrasjon**
3. Velg **Statens vegvesen DATEX**
4. Skriv inn:

   * Brukernavn
   * Passord
   * Vegobjekt (f.eks. Måløybrua)
   * Eventuelt koordinater / radius

Etter oppsett vil sensorer automatisk bli tilgjengelige i Home Assistant.

---

## 📊 Eksempel på entiteter

* `binary_sensor.maloybrua_stengt`
* `sensor.maloybrua_status`
* `sensor.maloybrua_hendelse`
* `sensor.maloybrua_vind`

---

## 🚧 Status

Dette prosjektet er **under aktiv utvikling**.
API-struktur og sensorlogikk kan endres etter hvert som flere DATEX-felt testes.

---

## 🤝 Bidrag

Bidrag er svært velkomne!

* Issues for feil og forbedringer
* Pull requests for nye funksjoner
* Testere med tilgang til DATEX oppfordres spesielt

---

## 📄 Lisens

MIT License

---


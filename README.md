# Health — dashboard local Google Health / Fitbit Air

Pipeline local (DuckDB + Streamlit) qui transforme les exports Google Takeout
"Google Health" en tableaux de bord orientés renforcement musculaire et perte
de graisse abdominale. Ré-exécutable à chaque nouvel export sans doublon.

## Mettre à jour avec un nouvel export

1. Exporte tes données depuis [Google Takeout](https://takeout.google.com)
   (uniquement "Google Health"), dézippe.
2. Copie le dossier `Google Health/` dans `data/exports/AAAA-MM-JJ/` (date de
   l'export).
3. Lance :
   ```powershell
   .\update.ps1
   ```
   Ça ingère le dernier export (les fichiers déjà vus sont sautés via leur
   SHA-256, donc rapide même en cas de gros export), reconstruit les tables
   `mart.*`, puis ouvre le dashboard.

Pour ingérer sans lancer l'app : `.\update.ps1 -NoLaunch`
Pour rejouer tous les exports : `python -m health.ingest --all`

**Après un changement de la logique de parsing** (`health/loaders.py`), il faut
`python -m health.ingest --all --reparse` : le saut par SHA-256 empêche sinon un
fichier déjà vu d'être relu, et les corrections ne s'appliqueraient pas aux
données déjà en base.

## Installation

```powershell
pip install -r requirements.txt
```

### Profil personnel

L'app lit ton profil (sexe, date de naissance, taille, poids) depuis l'export
Takeout lui-même, table `raw.user_profile`. Aucune configuration n'est donc
nécessaire dans le cas normal.

Un repli existe pour les cas où l'export n'a pas encore été ingéré. Il ne vit
**pas** dans le code : une date de naissance et un poids sont des données de
santé identifiantes, et un fichier versionné les grave dans l'historique du
dépôt — d'où on ne les retire plus. Crée si besoin `data/profile.json`, qui est
ignoré par git :

```json
{
  "sex": "MALE",
  "birth_date": "1990-01-01",
  "height_cm": 175.0,
  "weight_kg": 70.0
}
```

Sans ce fichier, `health/config.py` utilise des valeurs génériques.

## Structure

```
data/
  exports/AAAA-MM-JJ/Google Health/   exports Takeout bruts (non versionnés)
  warehouse/health.duckdb             entrepôt (non versionné)
health/
  sources.py        registre déclaratif des datasets ingérés
  loaders.py        lecture/normalisation CSV et JSON
  ingest.py         ingestion idempotente (CLI) + macros SQL partagées
  enrich.py         mapping mouvement -> groupe musculaire (movements.yaml)
  profile.py        profil utilisateur lu depuis l'export
  metrics.py        registre des métriques (libellé, unité, sens, provenance)
  stats.py          baselines, tendances, CTL/ATL/TSB, corrélations corrigées
  sql/              construction des tables mart.*
app/
  Bilan_du_jour.py  page d'accueil — suis-je en forme ce jour-là, et pourquoi
  pages/            Progression, Entraînement, Récupération, Dépense,
                    Explorateur, Glossaire (les noms de fichiers portent leurs
                    accents : Streamlit en tire le libellé de navigation)
  charts.py         composants de visualisation partagés
  ui.py             carte, grille de KPI, bande de jours, bandeaux
  theme.py          tokens clair/sombre, CSS, règle des séparateurs
  static/mark.svg   monogramme (arc de jauge), posé par st.logo
tests/              idempotence, cohérence des marts, statistiques, registre
```

## Les deux modules à connaître

`health/metrics.py` est la source de vérité de tout l'affichage : une métrique y
est définie une fois (libellé, unité, sens de lecture, ce qu'elle mesure,
comment l'interpréter, d'où elle vient), et cette définition alimente les titres
de graphes, les infobulles, les couleurs de statut et la page Glossaire.
Ajouter une métrique au dashboard = ajouter une entrée dans ce fichier.

`health/stats.py` fournit ce qui rend un chiffre lisible : baseline personnelle
(médiane et MAD glissants sur fenêtre calendaire), z-score robuste, tendance
avec intervalle de confiance et p-value, modèle de forme CTL/ATL/TSB, et
corrélations avec correction de Benjamini-Hochberg.

**Provenance des chiffres** — trois natures différentes, distinguées partout
dans l'interface : les *mesures* de l'appareil (pas, FC, minutes de sommeil),
les *scores propriétaires Fitbit* non reproductibles (readiness, score de
sommeil, charge cardio, ACWR) et les valeurs *calculées ici* avec une formule
vérifiable (BMR, CTL/ATL/TSB, dette de sommeil, z-scores).

## Tests

```powershell
python -m pytest tests/ -v
```

## Ce qui est ingéré

Sources primaires (`Physical Activity_GoogleData` et
`Health Fitness Data_GoogleData`), plus le VO2max, les zones de FC
personnelles, les objectifs d'activité et le profil, filtrées à partir du
**17/06/2026** (port du Fitbit Air). Volontairement exclus :
`UserActivityProbabilities` / `UserSensorCompressionToken` (1.2 Go de sorties de
classifieur ML sans valeur analytique), `micro_motion`, `micro_stillness`,
`live_pace`, `body_temperature` intraday, et les journaux nutrition/hydratation
(trop lacunaires pour être fiables).

Le poids/taille ne sont connus qu'à un seul point dans le temps (pas de
balance compatible avec le Fitbit Air) : pas de suivi de recomposition
corporelle pour l'instant. Le schéma `data/manual/` est prévu pour y ajouter
un `body.csv` rempli à la main plus tard si besoin.

## Limites connues des données

À lire avant de tirer une conclusion d'un graphe :

- **Historique court.** 39 jours et 6 semaines. La plupart des tendances ne sont
  pas statistiquement significatives, et le dashboard l'affiche plutôt que de
  tracer une courbe rassurante. Le modèle de forme CTL demande 42 jours pour
  être mûr : avant, il est signalé « en construction ».
- **Pas et distance : une seule source par jour.** La montre et le téléphone
  comptent tous les deux ; les additionner doublait les totaux. La montre est
  prioritaire (ses pas et sa distance sont cohérents entre eux), et la source
  retenue est exposée dans `steps_source` / `distance_source`.
- **Points AZM ≠ minutes.** Fitbit compte 2 points par minute en zone
  cardio/pic. Les colonnes s'appellent donc `azm_points_*`.
- **Volume de renfo partiellement reconstruit.** La source ne renseigne le début
  d'une série que dans un tiers des cas ; il est déduit de la fin du repos
  précédent (`duration_is_estimated`). Une séance de l'export n'a aucun
  horodatage et n'existe donc qu'en nombre de séries.
- **Scores propriétaires en calibration.** Le readiness et la charge cardio ne
  sont pas fiables avant la fin de la calibration de l'appareil
  (`readiness_in_calibration`, `cardio_load_in_calibration`).
- **Jours partiels.** Le premier jour de port et le jour de l'export sont
  incomplets (`is_partial_day`) et exclus des moyennes.
- **Aucun bilan énergétique possible.** L'export ne contient aucun apport
  alimentaire exploitable (`nutrition_log` a des nutriments vides).

## Ajouter un dataset

Ajoute une entrée à `PHYSICAL_ACTIVITY` ou `HEALTH_FITNESS` dans
`health/sources.py` (nom, dossier, motif de fichier, colonnes timestamp),
relance `python -m health.ingest --all`.

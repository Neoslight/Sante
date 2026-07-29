"""Page « Entraînement » : est-ce que je m'entraîne comme il faut ?

Une seule question, et deux moitiés qui n'en font qu'une : COMBIEN j'en fais, et
est-ce BIEN RÉPARTI. La progression (ce que le corps est devenu) vit sur
« Progression », la forme du jour sur le « Bilan » — ici, c'est ce qu'on FAIT.

Trois règles tenues de bout en bout :

* **La semaine en cours ne compte pas.** `mart.weekly` produit une ligne dès le
  premier jour d'une semaine : la dernière ne couvre que les jours écoulés. La
  version précédente comparait cette ligne-là à une semaine pleine et annonçait
  donc une chute de volume tous les lundis. Tout ce qui est hebdomadaire — le
  verdict, les tuiles, les barres empilées — s'arrête à la dernière semaine
  CLOSE ; seul le grain quotidien (charge, assiduité, journal) va jusqu'au bout.
* **Une séance n'est comptée qu'une fois.** Les séances guidées existent dans
  DEUX tables : `mart.workouts` les porte avec `workout_kind = 'renfo'`, et
  `mart.strength_sessions` les détaille. La page affichait les deux tableaux
  côte à côte sans le dire. Le journal ne prend donc que le cardio de la
  première, et les séances de renforcement de la seconde.
* **Le verdict décide dans `health.stats`, la page ne fait que le rendre.**
  Même règle que `day_verdict` sur le Bilan et `progress_verdict` sur
  Progression : quatre graphes empilés laissaient le lecteur composer lui-même
  la réponse à la question posée en titre.
"""
import datetime as dt
import html
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pandas as pd
import streamlit as st

import charts
import common
import queries
import theme
import ui
from health import metrics as metrics_mod
from health import stats
from health.metrics import require as metric

st.set_page_config(page_title=common.PAGE_TITLE.format("Entraînement"), layout="wide")
theme.inject_css()

#: Hauteurs de graphe : DEUX valeurs, une par largeur de colonne — mêmes que
#: « Progression ». Ce qui doit se conserver d'un graphe à l'autre n'est pas la
#: hauteur mais la proportion.
CHART_HEIGHT = 300
CHART_HEIGHT_HALF = 240

#: Fenêtre de la normale d'une grandeur HEBDOMADAIRE, en jours calendaires.
#:
#: Les 28 jours par défaut de `stats.rolling_baseline` ne contiendraient que
#: quatre lignes de `mart.weekly`, sous le `min_periods` de 5 : toutes les
#: normales sortiraient vides et les tuiles n'auraient ni pointillé ni couleur.
#: Douze semaines est le premier palier où une médiane glissante hebdomadaire a
#: de quoi se calculer sans écraser la saison.
WEEK_BASELINE_DAYS = 84
WEEK_BASELINE_MIN_WEEKS = 4

#: Référence des pastilles : la MÉDIANE des quatre semaines closes précédentes,
#: et non la semaine d'avant. Comparer deux points uniques d'une série bruitée
#: fabrique une tendance à partir de deux accidents — c'est l'argument de
#: `stats.long_term_reference`, transposé à la semaine.
KPI_REFERENCE_WEEKS = 4

#: Une semaine close dont moins de cinq jours ont été réellement mesurés sort de
#: la RÉFÉRENCE, pas des graphes. Les sommes de `mart.weekly` (charge, points
#: d'activité) ne filtrent pas les jours partiels, contrairement aux moyennes :
#: une semaine à trois jours de port tire la médiane vers le bas et ferait
#: passer une semaine ordinaire pour une bonne semaine.
MIN_MEASURED_DAYS = 5

#: Au-delà, un mouvement est « délaissé ». Deux semaines, soit l'intervalle
#: au-delà duquel un mouvement pratiqué une fois par semaine a manifestement
#: sauté son tour.
STALE_DAYS = 14

#: Les tuiles, dans l'ordre de lecture : ce que la charge a coûté au système
#: cardio, puis ce que le renforcement a produit.
KPI_KEYS = ["cardio_load_total", "azm_points_total", "total_work_minutes",
            "strength_sessions_count"]

#: Comptes dont un ZÉRO est une rupture et non le bas d'une échelle : une
#: semaine sans aucune séance est un fait discret, une semaine à charge cardio
#: basse est un point sur un continuum. Ces zéros deviennent des FAITS du
#: verdict (`stats.training_verdict(facts=...)`) parce qu'aucun z-score ne peut
#: les porter et qu'une tuile n'a pas le droit d'afficher un indicateur que ses
#: voisines n'ont pas (cf. `charts.kpi_card`).
ZERO_IS_A_BREAK: dict[str, str] = {
    "strength_sessions_count": "aucune séance cette semaine",
}

#: Hauteur d'une ligne de `st.dataframe`, en pixels, plus celle de l'en-tête.
#: Streamlit dimensionne sa table sur un nombre de lignes par défaut et ROGNE la
#: dernière au lieu de la faire défiler : la ligne du bas apparaissait coupée en
#: deux. Une hauteur explicite règle le cas, et plafonne la table à dix lignes
#: quand elle s'allonge — au-delà, elle défile.
ROW_PX, HEADER_PX, MAX_TABLE_ROWS = 35, 38, 10


def _table_height(n_rows: int) -> int:
    return HEADER_PX + ROW_PX * max(1, min(n_rows, MAX_TABLE_ROWS))

#: Signaux du verdict : nom de DOMAINE (celui qui entre dans la phrase) et
#: colonne hebdomadaire. Pas de métrique entre parenthèses — même règle que les
#: nuances du Bilan et de Progression.
SIGNAL_KEYS: list[tuple[str, str]] = [
    ("Volume", "total_work_minutes"),
    ("Séances", "strength_sessions_count"),
    ("Cardio", "azm_points_total"),
]
#: Le même nom de domaine, indexé par colonne — pour qu'un fait et une nuance
#: portant sur la même grandeur ne s'appellent pas différemment d'une ligne à
#: l'autre du verdict.
SIGNAL_KEYS_BY_COL: list[tuple[str, str]] = [(col, name) for name, col in SIGNAL_KEYS]

# =============================================================================
# Données : historique COMPLET d'abord, fenêtre ensuite.
#
# Le modèle CTL a besoin de tout le passé disponible (moyenne exponentielle sur
# 42 jours) : le calculer sur la seule fenêtre affichée le ferait repartir de
# zéro à chaque changement de fenêtre.
# =============================================================================
full_daily = queries.daily()
if full_daily.empty:
    st.info("Pas encore de données ingérées.")
    st.stop()

weekly_all = queries.weekly()
hi_date = pd.to_datetime(full_daily["local_date"]).max().date()

# =============================================================================
# En-tête : la question, et la fenêtre sur laquelle on y répond
# =============================================================================
# Pas de `st.title` : « Entraînement » répétait le nom de l'onglet juste à
# gauche, et son sous-titre gris portait la seule chose à lire. C'est la
# QUESTION qui tient l'en-tête, comme sur le Bilan et Progression.
with common.page_head("Est-ce que je m'entraîne comme il faut ?"):
    start, end, missing_days = common.weeks_picker()

d = queries.daily(start, end)
sets_df = queries.strength_sets(start, end)
sessions = queries.strength_sessions(start, end)
workouts_df = queries.workouts(start, end)

# La semaine en cours, écartée de tout ce qui est hebdomadaire (cf. docstring).
current_week_start = pd.Timestamp(hi_date - dt.timedelta(days=hi_date.weekday()))
weeks_all = weekly_all.copy()
if not weeks_all.empty:
    weeks_all["week_start"] = pd.to_datetime(weeks_all["week_start"])
    weeks_all = weeks_all.sort_values("week_start")
weeks_done = (weeks_all[weeks_all["week_start"] < current_week_start]
              if not weeks_all.empty else weeks_all)
weeks_window = (weeks_done[weeks_done["week_start"] >= pd.Timestamp(start)]
                if not weeks_done.empty else weeks_done)

ctl_full = stats.ctl_atl_tsb(full_daily, load_col="cardio_load_total")

# Profondeur d'historique et maturité du modèle : UN SEUL énoncé, et seulement
# s'il limite la lecture. Un badge qui confirme l'attendu dépense de l'attention
# pour rien — même règle que le badge de qualité du Bilan. Il remplace le
# `st.warning` pleine largeur que la page portait en travers de son premier
# écran pour dire une réserve de calcul.
#
# Le badge dit ce qu'il LIMITE, et rien de plus.
#
# `confidence_label` écrivait « n=5 semaines — trop peu pour conclure » à
# quelques centimètres d'un verdict qui, lui, concluait. La phrase générique
# était fausse par excès de portée : ces cinq semaines ne bornent que les
# comparaisons d'une semaine à l'autre — les nuances et les pastilles, qui ont
# besoin d'une médiane hebdomadaire. Le ratio de charge, lui, est calculé par
# l'appareil sur des JOURS (sept contre vingt-huit) et ne dépend pas du nombre
# de lignes hebdomadaires disponibles : le gèler sous huit semaines aurait
# supprimé une conclusion valide pour faire taire une phrase mal cadrée.
badge_parts: list[str] = []
n_weeks = len(weeks_window)
if n_weeks < 12:
    badge_parts.append(
        f"{n_weeks} semaine{'s' if n_weeks > 1 else ''} close{'s' if n_weeks > 1 else ''} "
        "— les comparaisons d'une semaine à l'autre restent indicatives"
    )
if missing_days:
    weeks_left = max(1, round(missing_days / 7))
    badge_parts.append(
        f"fenêtre réglable dans ~{weeks_left} semaine{'s' if weeks_left > 1 else ''} de mesures"
    )
if not ctl_full.empty:
    maturity = float(ctl_full.iloc[-1]["ctl_maturity"])
    if maturity < 1.0:
        # Espace INSÉCABLE avant le %, comme le veut la typographie française —
        # et insécable pour que « 93 % » ne se coupe jamais en fin de ligne.
        badge_parts.append(
            f"fond de forme mûr à {maturity * 100:.0f} % "
            f"(moyenne sur {stats.CTL_DAYS} jours)"
        )
if badge_parts:
    st.markdown(
        f'<span class="bevel-badge">'
        f'<span class="bevel-badge-dot" style="background:{theme.active_tokens()["ink_muted"]}">'
        f"</span>{html.escape(' · '.join(badge_parts))}</span>",
        unsafe_allow_html=True,
    )

t = theme.active_tokens()

# =============================================================================
# Normales hebdomadaires : UN SEUL calcul par colonne, partagé entre le verdict
# et les tuiles.
#
# Le verdict lit le z de la dernière semaine close, la tuile affiche le même z
# en couleur et sa baseline en pointillé. Deux calculs pour la même grandeur
# finissent toujours par diverger — c'est la faute que `compute.baseline_and_z`
# a déjà supprimée sur le Bilan.
# =============================================================================
_WEEKLY_CACHE: dict[str, tuple[pd.DataFrame, pd.Series]] = {}


def _weekly_baseline_z(col: str) -> tuple[pd.DataFrame, pd.Series]:
    """`(baseline, z)` d'une colonne de `mart.weekly`, sur les semaines closes."""
    if col in _WEEKLY_CACHE:
        return _WEEKLY_CACHE[col]
    empty = (pd.DataFrame(), pd.Series(dtype=float))
    if weeks_done.empty or col not in weeks_done.columns:
        _WEEKLY_CACHE[col] = empty
        return empty
    src = weeks_done.dropna(subset=[col])
    if len(src) < WEEK_BASELINE_MIN_WEEKS:
        _WEEKLY_CACHE[col] = empty
        return empty
    base = stats.rolling_baseline(
        src, col, date_col="week_start",
        window_days=WEEK_BASELINE_DAYS, min_periods=WEEK_BASELINE_MIN_WEEKS,
    )
    z = stats.robust_z(
        src, col, date_col="week_start",
        window_days=WEEK_BASELINE_DAYS, min_periods=WEEK_BASELINE_MIN_WEEKS,
        baseline=base,
    )
    _WEEKLY_CACHE[col] = (base, z)
    return base, z


def _last_weekly_z(col: str) -> float | None:
    _base, z = _weekly_baseline_z(col)
    if not len(z) or pd.isna(z.iloc[-1]):
        return None
    return float(z.iloc[-1])


# =============================================================================
# Charge : UNE affirmation, ses nuances en dessous.
#
# Le CTL, l'ATL et le TSB avaient chacun leur graphe ici, alors que le Bilan
# possède la forme du jour et Progression le niveau de fond : trois courbes
# pour un discours déjà tenu deux fois ailleurs. Ce qui manquait, à l'inverse,
# c'était une réponse. L'ACWR la porte — c'est la seule grandeur de la page qui
# compare ce qu'on vient de faire à ce qu'on a l'habitude de faire.
# =============================================================================
acwr_hist = full_daily.loc[
    pd.to_datetime(full_daily["local_date"]) <= pd.Timestamp(end)
] if "acwr_ratio" in full_daily.columns else pd.DataFrame()
acwr_valid = acwr_hist.dropna(subset=["acwr_ratio"]) if not acwr_hist.empty else pd.DataFrame()

# LA MÊME valeur que celle écrite au bout de la courbe, pas le point brut du jour.
#
# Le verdict lisait `acwr_ratio` de la dernière journée (0,92) pendant que le
# graphe juste en dessous étiquetait sa moyenne glissante (0,74) : deux nombres
# sous un seul nom, sans rien à l'écran pour dire lequel décide — et ils ne
# tombaient même pas du même côté de la plage soutenable. Le lissage est
# reproduit à l'identique de `charts.metric_chart` (fenêtre CALENDAIRE de
# `metric.ma_window`, mêmes `min_periods`) : deux formules pour la même courbe
# divergeraient au premier réglage.
_m_acwr = metric("acwr_ratio")
acwr_smoothed = pd.Series(dtype=float)
if not acwr_valid.empty:
    acwr_smoothed = (
        acwr_valid.set_index(pd.to_datetime(acwr_valid["local_date"]))["acwr_ratio"]
        .rolling(f"{_m_acwr.ma_window}D", min_periods=max(2, _m_acwr.ma_window // 3))
        .mean()
        .dropna()
    )
acwr_val = float(acwr_smoothed.iloc[-1]) if not acwr_smoothed.empty else None

# Variation relative du fond de forme, calculée AVANT le verdict : c'est elle
# qui l'empêche de conseiller « continue » au-dessus d'un fond qui s'effondre
# (cf. `stats.BASE_DROP`). Le constat affiché plus bas réutilise exactement ces
# deux valeurs — une seule référence par page.
ctl_was, ctl_lag, ctl_now = None, 0, None
m_ctl = metric("ctl")
if not ctl_full.empty:
    ctl_as_of = pd.to_datetime(ctl_full["local_date"]).max().date()
    ctl_src = ctl_full.loc[pd.to_datetime(ctl_full["local_date"]).dt.date <= ctl_as_of]
    ctl_was, ctl_lag = stats.long_term_reference(
        ctl_src, "ctl", ctl_as_of,
        lag_days=(ctl_as_of - pd.Timestamp(start).date()).days,
        half_window=7, min_lag_days=28,
    )
    ctl_smoothed = (
        ctl_src.set_index(pd.to_datetime(ctl_src["local_date"]))["ctl"]
        .rolling(f"{m_ctl.ma_window}D", min_periods=max(2, m_ctl.ma_window // 3))
        .mean().dropna()
    )
    ctl_now = float(ctl_smoothed.iloc[-1]) if not ctl_smoothed.empty else None
base_change = ((ctl_now - ctl_was) / ctl_was
               if ctl_was and ctl_now is not None else None)

def _last_closed_week(col: str) -> float | None:
    """Valeur de la dernière semaine CLOSE pour `col`, `None` si indisponible."""
    if weeks_done.empty or col not in weeks_done.columns:
        return None
    vals = weeks_done[col].dropna()
    return float(vals.iloc[-1]) if not vals.empty else None


# Les zéros qui comptent, en toutes lettres (cf. ZERO_IS_A_BREAK).
zero_facts = [
    (dict(SIGNAL_KEYS_BY_COL).get(col, metric(col).short), phrase, "serious")
    for col, phrase in ZERO_IS_A_BREAK.items()
    if _last_closed_week(col) == 0
]

verdict = stats.training_verdict(
    acwr_val, _m_acwr.good_range,
    {name: (_last_weekly_z(col), metric(col).direction) for name, col in SIGNAL_KEYS},
    base_change=base_change,
    facts=zero_facts,
)

with ui.card("Charge", info={
    "Le verdict": "Il ne juge QUE le rapport entre la charge de la semaine écoulée et "
                  "celle des dernières semaines (l'ACWR ci-dessous). C'est la seule "
                  "grandeur qui dise si ce que tu viens de faire est en ligne avec ce "
                  "que ton corps a l'habitude d'encaisser — un gros volume n'est pas un "
                  "problème, une AUGMENTATION rapide en est un.",
    "Les nuances": "Volume sous tension, séances de renforcement et minutes actives, "
                   "comparés chacun à TA normale des douze dernières semaines. Seuls les "
                   "écarts d'au moins un écart-type sont affichés : en deçà, il n'y a "
                   "rien à dire.",
    "Pourquoi la semaine en cours est absente": "Une semaine arrêtée un mardi n'est pas "
                                                "comparable à des semaines pleines. Tout "
                                                "ce qui se compte par semaine sur cette "
                                                "page s'arrête à la dernière semaine "
                                                "close ; la courbe ci-dessous, qui est "
                                                "quotidienne, va jusqu'au dernier jour "
                                                "connu.",
    "Où sont la forme et le fond": "La forme du jour (fond moins fatigue) est le verdict "
                                   "du Bilan, le niveau de fond sur plusieurs mois est "
                                   "sur « Progression ». Ici, c'est ce que tu FAIS, pas "
                                   "ce que ton corps en a fait — le constat de fond de "
                                   "forme ci-dessous est le seul pont entre les deux.",
    "L'ACWR": metric("acwr_ratio").how_read,
    "Lire le graphe": "Les points fins sont le ratio jour par jour — un point, une "
                      "journée. Le trait épais est leur moyenne glissante, avec sa "
                      "valeur écrite au bout : c'est ELLE que lit le verdict, pas le "
                      "point du jour, qui saute trop d'un jour à l'autre pour trancher "
                      "quoi que ce soit. La bande verte est la plage soutenable, et la "
                      "seule graduation de l'axe est le 1 : au-dessus tu fais plus que "
                      "d'habitude, en dessous moins.",
}):
    # Nuances FUSIONNÉES quand elles disent la même chose : trois lignes de
    # « dans ta normale » portent un seul bit d'information (cf.
    # `stats.merge_nuances`).
    nuance_html = ""
    for rank, (name, phrase, nst, _z) in enumerate(
        stats.merge_nuances(verdict.nuances, span_days=n_weeks * 7)
    ):
        # Budget couleur identique au Bilan : seule la nuance dominante, et
        # seulement si elle demande une décision, porte sa couleur de statut.
        is_dominant = rank == 0 and nst in charts.ATTENTION_STATUSES
        glyph_color = charts.status_hex(nst, t) if is_dominant else t["ink_muted"]
        nuance_html += (
            f'<div class="bevel-nuance">'
            f'<span class="bevel-flag" style="color:{glyph_color}" '
            f'title="{html.escape(charts.STATUS_LABELS[nst])}">'
            f"{charts.STATUS_GLYPHS[nst]}</span>"
            f"<span>{html.escape(name)} — {html.escape(phrase)}</span></div>"
        )

    # Le fond de forme EN CONSTAT, et non en nuance : sa pente n'est pas
    # testable (moyenne exponentielle sur 42 jours, mesures non indépendantes),
    # mais un déplacement chiffré n'est pas une inférence — c'est une
    # soustraction. C'est aussi la seule chose que cette page puisse dire de
    # l'EFFET de la charge qu'elle décrit. Calqué sur « Progression », au chiffre
    # et à la teinte près.
    # `ctl_was` / `ctl_now` viennent du calcul fait plus haut, celui-là même qui
    # a nourri le verdict : le constat et la phrase de tête ne peuvent donc plus
    # se contredire, puisqu'ils lisent le même couple de nombres.
    aside_html = ""
    if ctl_was is not None and ctl_now is not None:
        span = (f"{round(ctl_lag / 7)} dernières semaines" if ctl_lag >= 10
                else f"{ctl_lag} derniers jours")
        # Teinte d'IDENTITÉ du fond de forme, pas une couleur de statut : elle
        # dit de quelle courbe on parle, elle ne juge pas le sens.
        ctl_hue = t["series"][m_ctl.palette_index % len(t["series"])]
        spark = charts.micro_sparkline(
            ctl_smoothed.tail(ctl_lag + 1), ctl_hue, width=60, height=16,
        )
        aside_html = (
            f'<div class="bevel-verdict-aside">'
            f'<div class="bevel-verdict-aside-line">'
            f"<span>Fond de forme <b>{m_ctl.format(ctl_was)} → {m_ctl.format(ctl_now)}</b> "
            f"sur les {span}</span>"
            f'<span class="bevel-aside-delta" style="color:{ctl_hue}">'
            # Écart calculé sur les valeurs ARRONDIES, celles que le lecteur a
            # sous les yeux.
            f"{m_ctl.format_delta(m_ctl.rounded(ctl_now) - m_ctl.rounded(ctl_was))}</span>"
            f'<span class="bevel-aside-spark">{spark}</span></div>'
            f"<i>Niveau, non testé — c'est ce que la charge a construit, "
            f"pas un jugement sur elle.</i></div>"
        )

    # Corps du verdict indexé sur ce qu'il affirme : un statut neutre est par
    # définition une non-réponse, et l'écrire au corps réservé aux affirmations
    # d'état lui donnerait l'autorité d'une conclusion qu'il refuse de tirer.
    soft = " bevel-verdict-soft" if verdict.status == "neutral" else ""
    # Le ratio en chiffre, à côté de la phrase et à la même taille : c'est LE
    # nombre du verdict, il n'a rien à faire en gris pâle plus bas dans la carte
    # (même règle que le TSB sur le Bilan). Formaté par le registre, donc à la
    # française — le séparateur décimal ne se corrige pas à la main.
    score = (f'<span class="bevel-verdict-score">'
             f"{_m_acwr.format(acwr_val)}</span>"
             if acwr_val is not None else "")
    st.markdown(
        f'<div class="bevel-verdict">'
        f'<div class="bevel-verdict-headline{soft}">{html.escape(verdict.headline)}{score}</div>'
        f'<div class="bevel-verdict-hint">{html.escape(verdict.hint)}</div>'
        f"{nuance_html}{aside_html}</div>",
        unsafe_allow_html=True,
    )

    if acwr_valid.empty:
        ui.empty_state(
            "Pas encore de ratio de charge",
            hint="Il faut environ quatre semaines de charge cardio pour que l'appareil "
                 "puisse comparer la semaine écoulée aux précédentes.",
        )
    else:
        def _annotate_acwr(fig) -> None:
            """Nommer ce que le graphe montre déjà, sans rien y ajouter.

            Trois choses n'étaient nulle part : la bande verte — qui est le
            SEUIL DU VERDICT et occupait pourtant le tiers haut du cadre comme
            un vide ; le repère 1, seule graduation de l'axe, dont rien ne
            disait qu'il vaut « comme d'habitude » ; et les points gris, qui se
            lisaient comme du bruit faute d'être nommés.

            Posé ici et non dans `charts.metric_chart` : cette lecture est
            propre au ratio. Sur une VO2max ou une HRV, la bande verte est une
            zone de référence physiologique et le 1 ne veut rien dire.
            """
            lo_r, hi_r = _m_acwr.good_range
            fig.add_annotation(
                xref="paper", x=0.01, y=(lo_r + hi_r) / 2, yanchor="middle",
                text="plage soutenable", showarrow=False, xanchor="left",
                font=dict(color=t["status"]["good"], size=11),
            )
            fig.update_yaxes(
                tickmode="array", tickvals=[1.0],
                ticktext=["1 — comme d'habitude"],
                tickfont=dict(color=t["ink_muted"], size=11),
            )

        charts.metric_block(d, metric("acwr_ratio"), title="", height=CHART_HEIGHT,
                            decorate=_annotate_acwr)

# =============================================================================
# Repères chiffrés : combien j'en fais, par semaine.
#
# Différence assumée avec les tuiles du Bilan : là-bas la pastille compare une
# JOURNÉE à la normale glissante sur 28 jours, ici une SEMAINE close à la
# médiane des quatre précédentes. Deux grains, deux références — et la légende
# de la carte dit laquelle.
# =============================================================================


def _render_kpi(key: str) -> None:
    m = metric(key)
    if weeks_window.empty or key not in weeks_window.columns:
        charts.kpi_card(m, None, key=f"train_{key}")
        return

    series = weeks_window.set_index("week_start")[key]
    valid = series.dropna()
    value = float(valid.iloc[-1]) if not valid.empty else None

    # Référence : les semaines closes ANTÉRIEURES à celle qui est affichée, et
    # seulement celles dont la mesure tient (cf. MIN_MEASURED_DAYS).
    prev_value = None
    if value is not None:
        pool = weeks_done.loc[weeks_done["week_start"] < valid.index[-1]]
        if "days_complete" in pool.columns:
            pool = pool[pool["days_complete"].fillna(0) >= MIN_MEASURED_DAYS]
        ref = pool[key].dropna().tail(KPI_REFERENCE_WEEKS) if key in pool.columns else pd.Series(dtype=float)
        if not ref.empty:
            prev_value = float(ref.median())

    base_df, z_full = _weekly_baseline_z(key)
    z_last = float(z_full.iloc[-1]) if len(z_full) and pd.notna(z_full.iloc[-1]) else None
    baseline_last, band_last = None, None
    if not base_df.empty:
        valid_base = base_df.dropna(subset=["baseline"])
        if not valid_base.empty:
            baseline_last = float(valid_base["baseline"].iloc[-1])
            lo_b, hi_b = valid_base["lower"].iloc[-1], valid_base["upper"].iloc[-1]
            if pd.notna(lo_b) and pd.notna(hi_b):
                band_last = (float(lo_b), float(hi_b))

    charts.kpi_card(
        m, value, prev_value, series=series, z=z_last, key=f"train_{key}",
        delta_label=f"vs tes {KPI_REFERENCE_WEEKS} semaines précédentes",
        baseline=baseline_last, band=band_last,
    )


with ui.card("Repères", info={
    "Le grain": "Une tuile = UNE semaine, la dernière close. Les chiffres du Bilan sont "
                "des journées : un même nom de métrique n'y porte donc pas le même ordre "
                "de grandeur, ce ne sont pas deux mesures contradictoires mais deux "
                "unités de temps.",
    "La pastille": "Elle compare cette semaine à la MÉDIANE des quatre semaines closes "
                   "précédentes, pas à la semaine d'avant : deux semaines isolées "
                   "suffisent à fabriquer une tendance à partir de deux accidents. Les "
                   "semaines dont moins de cinq jours ont été mesurés sont écartées de "
                   "cette référence.",
    "La sparkline": "Elle couvre la fenêtre choisie, une marche par semaine. La ligne "
                    "pointillée est ta normale sur douze semaines et la bande grise ta "
                    "fourchette habituelle.",
    "Pourquoi douze semaines": "Une normale glissante sur 28 jours ne verrait que quatre "
                               "points hebdomadaires — trop peu pour qu'une médiane et un "
                               "écart robuste veuillent dire quelque chose.",
}):
    if weeks_window.empty:
        ui.empty_state(
            "Aucune semaine close sur cette fenêtre",
            hint="Il faut au moins une semaine complète, du lundi au dimanche.",
        )
    else:
        first = weeks_window["week_start"].min().date()
        last = weeks_window["week_start"].max().date()
        span = (f"{common.format_fr_date(first, weekday=False, year=False)} → "
                f"{common.format_fr_date(last + dt.timedelta(days=6), weekday=False, year=False)}")
        st.markdown(
            f'<div class="bevel-card-caption">'
            f'<b style="color:{t["ink_primary"]}">{html.escape(span)}</b> · '
            f"{n_weeks} semaine{'s' if n_weeks > 1 else ''} close{'s' if n_weeks > 1 else ''}, "
            f"la semaine en cours n'est pas comptée</div>",
            unsafe_allow_html=True,
        )
        ui.kpi_row(KPI_KEYS, _render_kpi, per_row=4)

# =============================================================================
# Volume par groupe musculaire : UNE unité à la fois.
#
# La page montrait les minutes et les séries dans deux graphes côte à côte, avec
# une légende qui expliquait pourquoi les deux existent. Deux dessins de la même
# grandeur demandent au lecteur de faire la synthèse lui-même ; une bascule pose
# la même question et n'affiche qu'une réponse.
# =============================================================================
UNITS: dict[str, tuple[str, str]] = {
    "Minutes": ("_min", "minutes"),
    "Séries": ("_segments", "séries"),
}

with ui.card("Ce que je fais chaque semaine", info={
    "Les deux unités": "Une partie des séances n'a aucun horodatage à la source : elles "
                       "n'existent qu'en NOMBRE de séries, jamais en minutes. Et un "
                       "gainage de 45 secondes ne se compare pas à une série de squats "
                       "en temps. Les deux unités disent donc des choses différentes — "
                       "d'où la bascule, plutôt qu'un choix fait à ta place.",
    "Les durées reconstruites": "La source ne donne le début d'une série que dans un cas "
                                "sur trois ; ailleurs il est déduit de la fin du repos "
                                "précédent. La légende dit combien de séries sont dans ce "
                                "cas sur la fenêtre.",
    "Les groupes musculaires": "Chaque mouvement est rattaché à un groupe par une table "
                               "de correspondance maintenue à la main. Un mouvement "
                               "inconnu tombe dans « autre » — s'il y en a beaucoup, "
                               "c'est la table qu'il faut compléter.",
    "La semaine en cours": "Absente, comme partout où l'on compte par semaine : "
                           "incomplète, elle se lirait comme un décrochage.",
}):
    unit_choice = st.segmented_control(
        "Unité", list(UNITS.keys()), default="Minutes",
        label_visibility="collapsed", key="train-unit",
    ) or "Minutes"
    suffix, y_title = UNITS[unit_choice]

    if weeks_window.empty:
        ui.empty_state(
            "Aucune semaine close à afficher",
            hint="Le volume se compte par semaine complète, du lundi au dimanche.",
        )
    else:
        n_estimated = (int(sets_df["duration_is_estimated"].fillna(False).sum())
                       if "duration_is_estimated" in sets_df.columns else 0)
        if n_estimated and not sets_df.empty:
            st.markdown(
                f'<div class="bevel-card-caption">{n_estimated} série'
                f"{'s' if n_estimated > 1 else ''} sur {len(sets_df)} "
                f"{'ont' if n_estimated > 1 else 'a'} une durée reconstruite.</div>",
                unsafe_allow_html=True,
            )
        st.plotly_chart(
            charts.muscle_group_bar(weeks_window, "week_start", suffix=suffix,
                                    y_title=y_title, title="", height=CHART_HEIGHT),
            width="stretch",
        )

# =============================================================================
# Assiduité : le motif hebdomadaire, pas le total
# =============================================================================
with ui.card("Assiduité", info={
    "Ce que compte la grille": "Les minutes d'activité de chaque journée, cardio et "
                               "renforcement confondus, telles que l'appareil les a "
                               "enregistrées.",
    "Pourquoi une grille": "En ligne du temps, l'assiduité se noie dans le bruit "
                           "quotidien. Disposée en semaine × jour, c'est le MOTIF qui "
                           "ressort : quels jours décrochent, et si le décrochage se "
                           "répète.",
}):
    # Le rythme se compte sur les semaines CLOSES, la grille en montre une de
    # plus.
    #
    # « 28 jours sur 34 » sous un sélecteur réglé sur « 4 sem. » donnait deux
    # fenêtres pour un seul contrôle : la grille est quotidienne et va donc
    # jusqu'au dernier jour connu — c'est la règle de la page — mais sa dernière
    # colonne est une semaine entamée, qui ne peut pas entrer dans une moyenne
    # hebdomadaire sans la tirer vers le bas. Le chiffre porte sur les semaines
    # closes, et la colonne en cours est annoncée pour ce qu'elle est.
    active_note = ""
    if "workout_minutes" in d.columns and not d.empty:
        dd = d.copy()
        dd["local_date"] = pd.to_datetime(dd["local_date"])
        closed = dd[dd["local_date"] < current_week_start]
        if not closed.empty:
            active_days = int((closed["workout_minutes"].fillna(0) > 0).sum())
            # Virgule décimale : « 5.8 » est le seul nombre anglais qui aurait
            # traîné sur la page, tout le reste passe par le registre de
            # métriques (`Metric.format`), qui francise ses séparateurs.
            per_week = f"{active_days / len(closed) * 7:.1f}".replace(".", ",")
            active_note = (
                f"{active_days} jour{'s' if active_days > 1 else ''} avec activité "
                f"sur les {len(closed)} des semaines closes, soit {per_week} par "
                f"semaine · la dernière colonne est la semaine en cours"
            )
    if active_note:
        st.markdown(
            f'<div class="bevel-card-caption">{html.escape(active_note)}</div>',
            unsafe_allow_html=True,
        )
    st.plotly_chart(
        charts.calendar_heatmap(d, "workout_minutes", title="", height=CHART_HEIGHT_HALF,
                                unit="min"),
        width="stretch",
    )

# =============================================================================
# Équilibre : ce qui est travaillé, et ce qui ne l'est plus.
#
# Deux blocs qui posaient la même question dans deux cartes séparées — la
# répartition d'un côté, les mouvements oubliés de l'autre. Un déséquilibre et
# le mouvement qui l'explique se lisent ensemble ou pas du tout.
# =============================================================================
with ui.card("Équilibre musculaire", info={
    "Le radar": "La répartition sur la fenêtre choisie, dans l'unité sélectionnée plus "
                "haut. Une forme régulière dit un travail équilibré ; une pointe dit un "
                "groupe qui prend toute la place.",
    "« Délaissé »": f"Un mouvement dont la dernière pratique remonte à plus de "
                    f"{STALE_DAYS} jours avant la fin de la fenêtre. L'historique "
                    "consulté est COMPLET (il faut savoir quand un mouvement a été "
                    "pratiqué pour la dernière fois, même avant la fenêtre) mais borné à "
                    "la fin de période, pour que le sélecteur garde un effet visible.",
    "Le groupe « autre »": "Un mouvement que la table de correspondance ne connaît pas "
                           "encore. C'est un défaut de configuration, pas un défaut "
                           "d'entraînement.",
}):
    col_radar, col_stale = st.columns(2)

    with col_radar:
        if sets_df.empty or "muscle_group" not in sets_df.columns:
            ui.empty_state("Aucune série de renforcement sur cette fenêtre")
        else:
            if suffix == "_min" and "duration_seconds" in sets_df.columns:
                values = (sets_df.groupby("muscle_group")["duration_seconds"]
                          .sum().div(60.0).to_dict())
            else:
                values = sets_df["muscle_group"].value_counts().to_dict()
            st.plotly_chart(
                charts.radar(values, title="", height=CHART_HEIGHT,
                             unit="min" if suffix == "_min" else "séries"),
                width="stretch",
            )

    with col_stale:
        # Historique COMPLET, borné à la fin de la fenêtre : c'est la correction
        # de l'ancienne page, qui chargeait tout l'historique sans jamais tenir
        # compte de la période affichée — le sélecteur n'avait donc aucun effet
        # ici, et « aujourd'hui » ne correspondait pas à la fin de période.
        all_sets = queries.strength_sets()
        if not all_sets.empty:
            all_sets = all_sets[pd.to_datetime(all_sets["local_date"]) <= pd.Timestamp(end)]
        if all_sets.empty:
            ui.empty_state("Pas d'historique de renforcement")
        else:
            last_seen = (all_sets.groupby(["segment_name", "muscle_group"])["local_date"]
                         .max().reset_index())
            last_seen["jours"] = (
                pd.Timestamp(end) - pd.to_datetime(last_seen["local_date"])
            ).dt.days
            stale = last_seen[last_seen["jours"] >= STALE_DAYS].sort_values(
                "jours", ascending=False,
            )
            if stale.empty:
                st.markdown(
                    f'<div class="bevel-card-caption">Tous les mouvements ont été '
                    f"pratiqués dans les {STALE_DAYS} jours précédant la fin de la "
                    f"fenêtre.</div>",
                    unsafe_allow_html=True,
                )
            else:
                shown = stale.head(8)
                st.markdown(
                    f'<div class="bevel-card-caption">{len(stale)} mouvement'
                    f"{'s' if len(stale) > 1 else ''} sans pratique depuis "
                    f"{STALE_DAYS} jours ou plus"
                    f"{f', les {len(shown)} plus anciens ci-dessous' if len(stale) > len(shown) else ''}"
                    "</div>",
                    unsafe_allow_html=True,
                )
                # Ni horodatage brut ni identifiant technique à l'écran : la
                # table sortait « 2026-06-23 00:00:00 » et « haut_du_corps »,
                # là où le radar juste à gauche affiche « 23 juin » et « Haut du
                # corps ». Deux orthographes du même groupe dans une même carte
                # se lisent comme deux groupes différents.
                table = pd.DataFrame({
                    "Mouvement": shown["segment_name"].to_numpy(),
                    "Groupe": [charts.MUSCLE_GROUP_LABELS.get(g, g)
                               for g in shown["muscle_group"]],
                    "Dernière fois": [
                        common.format_fr_date(pd.Timestamp(v).date(),
                                              weekday=False, year=False)
                        for v in shown["local_date"]
                    ],
                    "Jours écoulés": shown["jours"].to_numpy(),
                })
                st.dataframe(charts.plain_table(table), width="stretch", hide_index=True,
                             height=_table_height(len(table)))

# =============================================================================
# Journal des séances : UNE liste, dédoublonnée.
#
# Les séances guidées vivaient dans deux tableaux voisins, l'un tiré de
# mart.workouts et l'autre de mart.strength_sessions, sans que rien ne dise
# qu'il s'agissait des mêmes séances comptées deux fois. Le cardio vient donc de
# la première, le renforcement de la seconde, et le lecteur voit ce qu'il a
# fait, pas d'où ça sort.
# =============================================================================


def _duration(value) -> str:
    """Durée en clair, « — » si elle manque.

    `metrics.format_duration` prend un nombre et n'a aucune raison de savoir
    quoi faire d'un trou : une séance sans horodatage de fin sort de la table
    avec une durée nulle, et `int(round(abs(nan)))` lève.
    """
    if value is None or pd.isna(value):
        return "—"
    return metrics_mod.format_duration(float(value))


def _session_rows() -> pd.DataFrame:
    rows: list[dict] = []
    if not workouts_df.empty and "workout_kind" in workouts_df.columns:
        cardio = workouts_df[workouts_df["workout_kind"] == "cardio"]
        for r in cardio.itertuples(index=False):
            hr = getattr(r, "avg_hr", None)
            kcal = getattr(r, "calories", None)
            rows.append({
                "_date": pd.Timestamp(getattr(r, "local_date")),
                "Séance": getattr(r, "activity_name", "—"),
                "Type": "Cardio",
                "Durée": _duration(getattr(r, "duration_min", None)),
                "Intensité": f"{hr:.0f} bpm" if pd.notna(hr) else "—",
                "Volume": f"{kcal:.0f} kcal" if pd.notna(kcal) else "—",
            })
    if not sessions.empty:
        for r in sessions.itertuples(index=False):
            rpe = getattr(r, "rpe", None)
            segs = getattr(r, "work_segments", None)
            rows.append({
                "_date": pd.Timestamp(getattr(r, "local_date")),
                "Séance": getattr(r, "workout_name", "—"),
                "Type": "Renforcement",
                "Durée": _duration(getattr(r, "duration_min", None)),
                # Un RPE non déclaré remonte à 0, et l'échelle commence à 1 :
                # « RPE 0/10 » affichait une difficulté nulle là où il n'y a
                # qu'une absence de réponse.
                "Intensité": f"RPE {rpe:.0f}/10" if pd.notna(rpe) and rpe > 0 else "—",
                "Volume": f"{segs:.0f} séries" if pd.notna(segs) else "—",
            })
    if not rows:
        return pd.DataFrame()
    out = pd.DataFrame(rows).sort_values("_date", ascending=False)
    out.insert(0, "Date", [
        common.format_fr_date(ts.date(), weekday=False, year=False) for ts in out["_date"]
    ])
    return out.drop(columns=["_date"])


with ui.card("Séances", info={
    "Deux sources, une liste": "Les séances guidées de renforcement sont enregistrées "
                               "deux fois par l'appareil : une fois comme exercice, une "
                               "fois avec le détail de leurs séries. Le journal prend le "
                               "cardio d'un côté et le renforcement de l'autre, pour "
                               "qu'aucune séance n'apparaisse en double.",
    "L'intensité": "Pour le cardio, la fréquence cardiaque moyenne de la séance. Pour le "
                   "renforcement, le RPE — la difficulté que TU as déclarée, de 1 à 10, "
                   "seule métrique subjective du tableau de bord et seule à capter ce que "
                   "les capteurs ne voient pas.",
    "Le détail intra-journalier": "Seul le cardio en a un : la courbe de fréquence "
                                  "cardiaque de la journée, avec tes bornes de zones "
                                  "recalculées ce jour-là.",
}):
    journal = _session_rows()
    if journal.empty:
        ui.empty_state("Aucune séance sur cette fenêtre")
    else:
        st.dataframe(charts.plain_table(journal), width="stretch", hide_index=True,
                     height=_table_height(len(journal)))

        cardio_opts = (workouts_df[workouts_df["workout_kind"] == "cardio"]
                       if "workout_kind" in workouts_df.columns else pd.DataFrame())
        if not cardio_opts.empty:
            with st.expander("Détail d'une séance cardio"):
                options = list(cardio_opts.itertuples(index=False))
                labels = [
                    f"{common.format_fr_date(pd.Timestamp(o.local_date).date(), weekday=False, year=False)}"
                    f" — {o.activity_name} ({_duration(o.duration_min)})"
                    for o in options
                ]
                idx = st.selectbox(
                    "Séance", range(len(options)), format_func=lambda i: labels[i],
                    label_visibility="collapsed", key="train-session",
                )
                chosen_date = str(pd.Timestamp(options[idx].local_date).date())
                hr_df = queries.heart_rate_intraday(chosen_date)
                if hr_df.empty:
                    ui.empty_state(
                        "Pas de fréquence cardiaque enregistrée ce jour-là",
                        hint="La montre n'a pas été portée, ou l'export ne couvre pas "
                             "encore cette journée.",
                    )
                else:
                    st.plotly_chart(
                        charts.intraday_hr(hr_df, queries.hr_zones(chosen_date),
                                           title="", height=CHART_HEIGHT),
                        width="stretch",
                    )

ui.dismissed_summary()

# Le même pied que le Bilan et Progression : la profondeur d'historique décide
# de ce que les normales hebdomadaires peuvent dire.
common.page_footer(full_daily)

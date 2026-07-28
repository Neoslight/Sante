"""Page « Progression » : est-ce que je progresse ?

Une seule question, et donc un seul périmètre : la condition CARDIO DE FOND.
VO2max en est la mesure de référence, FC de repos et variabilité cardiaque la
racontent à plus court terme, le fond de forme (CTL) dit la capacité réellement
construite par l'entraînement. Le volume de renforcement et l'assiduité, qui
vivaient ici en v1, ont rejoint « Entraînement » : ce sont des questions sur ce
qu'on FAIT, pas sur ce que le corps est devenu.

Deux règles tenues de bout en bout :

* **Une pente non significative n'est pas un progrès.** Chaque tendance passe
  par `health.stats.trend` (n, p, IC 95 %) et le verdict de tête par
  `health.stats.progress_verdict`, qui refuse de conclure sous dix points
  mesurés — et refuse aussi d'appeler « plateau » une pente simplement noyée
  dans le bruit, ce qui serait une affirmation là où il n'y a que du silence.
* **L'horizon se compte en mois.** Le sélecteur de la barre latérale, réglé sur
  quatorze jours, condamnait cette page à répondre « on ne peut pas savoir » en
  permanence. Elle a son propre sélecteur, en page (`common.horizon_picker`).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pandas as pd
import streamlit as st

import charts
import common
import compute
import queries
import theme
import ui
from health import quality, stats
from health.metrics import require as metric

st.set_page_config(page_title=common.PAGE_TITLE.format("Progression"), layout="wide")
theme.inject_css()

#: Les quatre métriques de la page, dans l'ordre de lecture. Le libellé est
#: celui qui entre dans les phrases du verdict — donc un nom de DOMAINE, pas la
#: métrique entre parenthèses, même règle que la carte « Forme » du Bilan.
TRACKED: list[tuple[str, str]] = [
    ("vo2_max", "VO2max"),
    ("resting_hr", "FC de repos"),
    ("hrv_rmssd", "Variabilité cardiaque"),
    ("ctl", "Fond de forme"),
]
#: La métrique de référence : c'est elle qui donne la phrase de tête quand elle
#: conclut. Sans arbitre, une seule métrique secondaire en hausse suffirait à
#: annoncer « tu progresses ».
PRIMARY = "VO2max"

#: Métriques admises dans le VERDICT — le fond de forme en est exclu, et c'est
#: un point de fond, pas un choix de mise en page.
#:
#: Le CTL est une moyenne exponentielle sur 42 jours : deux valeurs consécutives
#: partagent 41 jours de données. Une régression linéaire y suppose pourtant des
#: observations indépendantes, si bien que son erreur-type est massivement
#: sous-estimée et sa p-value sans valeur — la pente du CTL ressort « hautement
#: significative » à peu près toujours, avec un intervalle de confiance
#: artificiellement serré. La faire trancher le verdict revenait à laisser un
#: lissage décider à la place de la mesure.
#:
#: Sa courbe et sa tuile restent : lire un NIVEAU sur un graphe n'engage aucune
#: inférence. C'est le test de significativité qui n'a pas lieu d'être.
VERDICT_KEYS = ("vo2_max", "resting_hr", "hrv_rmssd")

#: Hauteur UNIQUE des graphes de la page. Pleine largeur ou demi-largeur ne
#: change pas la hauteur d'une ligne de lecture : deux hauteurs différentes dans
#: une même colonne se lisent comme un défaut d'alignement de la grille.
CHART_HEIGHT = 340

# =============================================================================
# Données : historique COMPLET d'abord, fenêtre ensuite.
#
# Le modèle CTL a besoin de tout le passé disponible (moyenne exponentielle sur
# 42 jours) : le calculer sur la seule fenêtre affichée le ferait repartir de
# zéro à chaque changement d'horizon, et un « fond en forte hausse » ne serait
# alors que l'amorçage du modèle.
# =============================================================================
full_daily = queries.daily()
if full_daily.empty:
    st.info("Pas encore de données ingérées.")
    st.stop()

ctl_full = stats.ctl_atl_tsb(full_daily, load_col="cardio_load_total")

# =============================================================================
# En-tête : la question, et l'horizon sur lequel on y répond
# =============================================================================
# Pas de `st.title` : « Progression » répétait le nom de l'onglet de navigation
# juste à gauche, et son sous-titre en `st.caption` gris pâle portait la seule
# chose à lire. C'est la QUESTION qui tient l'en-tête, comme la date longue le
# fait sur le Bilan.
with common.page_head("Est-ce que je progresse ?"):
    start, end = common.horizon_picker()

# Jours réellement MESURÉS uniquement : une journée à couverture partielle a une
# FC de repos et une HRV calculées sur quelques heures. Les laisser entrer dans
# une régression revient à faire dire une tendance à des artefacts de mesure.
# Même cadre de référence que le Bilan (`quality.reference_frame`), sans `keep` :
# ici aucun jour particulier n'est jugé, ils sont tous des points de la pente.
window = full_daily.loc[
    pd.to_datetime(full_daily["local_date"]).between(pd.Timestamp(start), pd.Timestamp(end))
]
measured = quality.reference_frame(window)
ctl_window = ctl_full.loc[
    pd.to_datetime(ctl_full["local_date"]).between(pd.Timestamp(start), pd.Timestamp(end))
]

if measured.empty:
    st.info("Aucune journée pleinement mesurée sur cet horizon.")
    st.stop()

# UN SEUL jour de référence pour toute la page : le dernier jour pleinement
# mesuré.
#
# `reference_frame` écarte les journées à couverture partielle — au 25 juillet,
# 66 % de couverture FC, donc écartée. Les tuiles lisaient chacune la dernière
# valeur non nulle de LEUR source : les trois métriques de mart.daily tombaient
# au 24, le fond de forme venait de `ctl_window` (que `reference_frame` ne filtre
# pas) et tombait au 25. Une même carte affichait donc trois tuiles à une date et
# une quatrième à une autre, sans qu'aucune ne soit datée — un « HRV 45 » là où
# le Bilan montre 20 se lit alors comme une contradiction plutôt que comme deux
# jours différents.
as_of = pd.to_datetime(measured["local_date"]).max().date()
# Dernier jour PRÉSENT dans la base, mesuré ou non : sert uniquement à savoir
# s'il faut expliquer l'écart. Quand les deux coïncident, il n'y a rien à
# expliquer et la légende reste une simple date.
hi_date = pd.to_datetime(full_daily["local_date"]).max().date()

# Profondeur d'historique, annoncée UNIQUEMENT si elle limite la lecture. Un
# badge « n=180 jours » confirmerait l'attendu et dépenserait de l'attention
# pour rien — même règle que le badge de qualité du Bilan.
n_measured = len(measured)
if n_measured < 90:
    st.markdown(
        f'<span class="bevel-badge">'
        f'<span class="bevel-badge-dot" style="background:{theme.active_tokens()["ink_muted"]}">'
        f"</span>{stats.confidence_label(n_measured)}</span>",
        unsafe_allow_html=True,
    )

# =============================================================================
# Verdict de progression : UNE affirmation, ses nuances en dessous.
#
# Calque de la carte « Forme » du Bilan, et pour la même raison : quatre graphes
# empilés laissaient le lecteur composer lui-même la réponse à la question posée
# en titre, alors que le sens d'une pente n'est pas lisible sans le registre (une
# FC de repos qui baisse est une bonne nouvelle) ni sans son n.
# =============================================================================
t = theme.active_tokens()


def _source(key: str) -> pd.DataFrame:
    """Le CTL vient du modèle, les trois autres de mart.daily filtré.

    Le modèle, lui, produit une ligne par jour CALENDAIRE : il faut le recadrer
    sur `as_of`, sinon sa tuile devance d'un jour les trois autres.
    """
    if key != "ctl":
        return measured
    return ctl_window.loc[pd.to_datetime(ctl_window["local_date"]).dt.date <= as_of]


trends = {
    label: (stats.trend(measured, key) if key in measured.columns else None,
            metric(key).direction)
    for key, label in TRACKED if key in VERDICT_KEYS
}
verdict = stats.progress_verdict(
    trends, primary=PRIMARY,
    units={label: metric(key).unit.rstrip() for key, label in TRACKED},
)

with ui.card("Progression", info={
    "Le verdict": "Il ne regarde QUE des pentes significatives : une régression dont "
                  "l'intervalle de confiance contient zéro ne dit rien, et l'afficher "
                  "comme un progrès serait inventer une nouvelle. La VO2max arbitre — "
                  "c'est la mesure de référence de la condition cardio ; les autres "
                  "nuancent.",
    "Quand rien ne conclut": "Deux verdicts disent l'absence de réponse, et aucun des "
                             "deux n'est un plateau. « Pas encore concluant » : sous dix "
                             "jours mesurés, aucune pente n'est même calculable. « Rien de "
                             "mesurable » : les pentes sont calculées, aucune ne dépasse "
                             "le bruit. Un plateau affirmerait que rien ne bouge — le "
                             "dire demanderait de prouver que la pente est nulle, ce "
                             "qu'une régression non significative ne fait jamais : elle "
                             "constate seulement qu'elle ne peut pas exclure zéro. Dans "
                             "les deux cas, élargis l'horizon.",
    "« Signaux contradictoires »": "Deux pentes concluent, dans des sens opposés — par "
                                   "exemple la VO2max qui monte et la FC de repos aussi. "
                                   "Les deux signaux sont réels ; c'est leur composition "
                                   "qui n'a pas de sens unique. Les nuances les listent.",
    "Les nuances": "Une ligne par métrique, celles qui vont dans le mauvais sens en "
                   "premier. La phrase donne le sens et l'ampleur de la pente ; le "
                   "nombre de jours, la p-value et l'intervalle de confiance sont dans "
                   "« Détail chiffré », d'un clic.",
    "Jours retenus": "Seules les journées réellement mesurées entrent dans les "
                     "régressions : une journée à couverture partielle a une FC de repos "
                     "calculée sur quelques heures, et la faire peser sur une tendance "
                     "revient à faire dire quelque chose à un artefact de mesure.",
    "Pourquoi pas le fond de forme": "Le CTL est une moyenne exponentielle sur 42 jours : "
                                     "deux valeurs voisines partagent 41 jours de données. "
                                     "Un test de significativité y suppose des mesures "
                                     "indépendantes et ressort donc « significatif » quoi "
                                     "qu'il arrive. Sa courbe est plus bas — c'est son "
                                     "niveau qui se lit, pas sa pente.",
}):
    nuance_html = ""
    for rank, (name, phrase, nst, _slope) in enumerate(verdict.nuances):
        # Budget couleur identique au Bilan : seule la nuance dominante, et
        # seulement si elle demande une décision, porte sa couleur de statut.
        is_dominant = rank == 0 and nst in charts.ATTENTION_STATUSES
        glyph_color = charts.status_hex(nst, t) if is_dominant else t["ink_secondary"]
        nuance_html += (
            f'<div class="bevel-nuance">'
            f'<span class="bevel-flag" style="color:{glyph_color}" '
            f'title="{charts.STATUS_LABELS[nst]}">{charts.STATUS_GLYPHS[nst]}</span>'
            f"<span>{name} — {phrase}</span></div>"
        )
    # Le fond de forme, EN CONSTAT et non en nuance.
    #
    # Sa pente n'est pas testable (moyenne exponentielle sur 42 jours, mesures
    # non indépendantes) et le verdict l'exclut à raison. Mais l'exclure du test
    # n'oblige pas à l'exclure du discours : c'est la seule des quatre séries qui
    # se déplace franchement, et la page annonçait « rien de mesurable » avec un
    # graphe descendant de 35 à 28 juste en dessous, sans rien à l'écran pour
    # expliquer l'écart. Un déplacement chiffré n'est pas une inférence — c'est
    # une soustraction, vraie quelle que soit l'autocorrélation de la série.
    aside_html = ""
    shift = stats.level_shift(_source("ctl"), "ctl", as_of, days=28)
    if shift is not None:
        was, now, real_days = shift
        m_ctl = metric("ctl")
        span = (f"{round(real_days / 7)} dernières semaines" if real_days >= 10
                else f"{real_days} derniers jours")
        aside_html = (
            f'<div class="bevel-verdict-aside">'
            f"Fond de forme : <b>{m_ctl.format(was)} → {m_ctl.format(now)}</b> "
            f"sur les {span} <span>(niveau, non testé)</span>"
            f"<i>Le fond de forme n'entre pas dans le verdict — c'est une moyenne "
            f"lissée, sa pente n'est pas testable.</i></div>"
        )
    st.markdown(
        f'<div class="bevel-verdict">'
        f'<div class="bevel-verdict-headline">{verdict.headline}</div>'
        f'<div class="bevel-verdict-hint">{verdict.hint}</div>'
        f"{nuance_html}{aside_html}</div>",
        unsafe_allow_html=True,
    )

    with st.expander("Détail chiffré"):
        for _key, label in TRACKED:
            if label not in trends:
                continue
            tr, _direction = trends[label]
            if tr is None:
                st.write(f"**{label}** · pas de régression calculable sur cette fenêtre")
                continue
            st.write(
                f"**{label}** · pente {tr.slope_per_week:+.3f}/semaine "
                f"(IC 95 % {tr.ci_low_per_week:+.3f} à {tr.ci_high_per_week:+.3f}) · "
                f"p = {tr.p_value:.3f} · R² = {tr.r2:.2f} · n = {tr.n} jours sur "
                f"{tr.span_days} jours d'étendue"
            )
        st.caption(
            "Une pente est retenue à p < 0,05 et n ≥ 10 (cf. `health.stats.trend`). "
            f"Sur cette fenêtre : {stats.confidence_label(n_measured)}."
        )

# =============================================================================
# VO2max : la métrique de référence, seule dans sa carte
# =============================================================================
with ui.card("VO2max — la mesure de référence", info=metric("vo2_max").how_read):
    if "vo2_max" not in measured.columns or measured["vo2_max"].dropna().empty:
        ui.empty_state(
            "Pas d'estimation de VO2max sur cette fenêtre",
            hint="Fitbit ne l'estime qu'après des séances de course avec GPS.",
        )
    else:
        st.plotly_chart(
            # `title=""` : la carte porte déjà « VO2max ». Le titre interne le
            # répétait et occupait la ligne où la note de tendance doit tenir.
            charts.metric_chart(measured, metric("vo2_max"), title="", show_trend=True,
                                show_confidence=True, height=CHART_HEIGHT),
            width="stretch",
        )

# =============================================================================
# Les deux signaux courts, côte à côte : ils racontent la même histoire que la
# VO2max à une échelle de temps où elle ne bouge pas encore.
# =============================================================================
with ui.card("FC de repos & variabilité cardiaque", info={
    metric("resting_hr").short: f"{metric('resting_hr').what} {metric('resting_hr').how_read}",
    metric("hrv_rmssd").short: f"{metric('hrv_rmssd').what} {metric('hrv_rmssd').how_read}",
    "Pourquoi les deux ensemble": "Elles bougent en miroir : une FC de repos qui descend "
                                  "pendant que la variabilité monte est la signature d'une "
                                  "condition qui s'améliore. Quand elles divergent, c'est "
                                  "généralement le signe d'autre chose que l'entraînement "
                                  "(sommeil, alcool, maladie).",
}):
    # Ici les titres internes RESTENT : la carte nomme les deux métriques d'un
    # seul tenant, rien ne dirait laquelle est à gauche. La note de tendance passe
    # alors en sous-titre du bloc, sous le titre et non par-dessus.
    # Hauteur explicite, et la MÊME que les graphes pleine largeur de la page :
    # laissée au défaut (320), elle donnait 340 sur la VO2max et le fond de forme
    # et 320 ici, soit deux hauteurs de graphe dans une même colonne de lecture.
    c1, c2 = st.columns(2)
    with c1:
        st.plotly_chart(
            charts.metric_chart(measured, metric("resting_hr"), show_trend=True,
                                show_confidence=True, height=CHART_HEIGHT),
            width="stretch",
        )
    with c2:
        st.plotly_chart(
            charts.metric_chart(measured, metric("hrv_rmssd"), show_trend=True,
                                show_confidence=True, height=CHART_HEIGHT),
            width="stretch",
        )

# =============================================================================
# Fond de forme : la capacité réellement construite
#
# C'est ce qui manquait le plus à la v1 : la page parlait de progression sans
# jamais montrer la grandeur que l'entraînement construit. Le verdict du jour
# (page Bilan) en montre la DIFFÉRENCE avec la fatigue ; ici, c'est le niveau
# lui-même, sur des mois.
# =============================================================================
with ui.card("Fond de forme (CTL)", info={
    "Ce que c'est": metric("ctl").how_read,
    "Ce que ce n'est pas": "Ni un score de performance, ni une note. C'est la charge "
                           "cardio absorbée en moyenne sur six semaines, en unité "
                           "arbitraire : seuls comptent le SENS et l'ampleur relative "
                           "du déplacement, pas la valeur absolue.",
    "Maturité du modèle": "La moyenne se calcule sur 42 jours. Tant que l'historique est "
                          "plus court, la courbe monte mécaniquement depuis zéro — c'est "
                          "l'amorçage du modèle, pas une progression. La portion grisée "
                          "au début du graphe est exactement cette zone : ce qui s'y "
                          "trouve n'est pas encore une mesure de ta capacité.",
}):
    # La zone d'amorçage se DESSINE, elle ne se raconte pas.
    #
    # C'est une propriété d'une portion de courbe : dite en légende sous le
    # graphe (« les 42 premiers jours »), elle demandait au lecteur de la
    # reporter lui-même sur l'axe des dates — travail que personne ne fait.
    warmup_until = (pd.to_datetime(ctl_full["local_date"]).min()
                    + pd.Timedelta(days=stats.CTL_DAYS))
    if ctl_window.empty:
        ui.empty_state(
            "Le modèle de forme n'atteint pas cette fenêtre",
            hint="Il lui faut de la charge cardio quotidienne sur plusieurs semaines.",
        )
    else:
        # NI `show_trend` NI `show_confidence` : l'annotation de tendance affiche
        # une pente et sa p-value, qui ne veulent rien dire sur une moyenne
        # exponentielle (cf. `VERDICT_KEYS`). Sur cette courbe, c'est le niveau
        # et le sens du déplacement qui se lisent, pas un test.
        st.plotly_chart(
            charts.metric_chart(ctl_window, metric("ctl"), title="",
                                height=CHART_HEIGHT, warmup_until=warmup_until,
                                warmup_label="amorçage du modèle"),
            width="stretch",
        )
        maturity = float(ctl_full["ctl_maturity"].iloc[-1]) if "ctl_maturity" in ctl_full else 1.0
        if maturity < 1.0:
            # DEUX chiffres, et pas un seul unifié : ce n'est pas la même
            # profondeur qui compte des deux côtés.
            #
            # La maturité du modèle se mesure en jours de CALENDRIER — la
            # moyenne exponentielle tourne à cadence quotidienne et
            # `impute_partial_load` bouche les trous, donc une journée mal
            # couverte compte quand même pour un jour d'amorçage. Les régressions
            # de cette page, elles, ne portent que sur les jours MESURÉS. Écrire
            # « 39 » là où le verdict annonce « n=37 » et le pied « 37 jours
            # mesurés » se lit comme une incohérence ; écrire « 37 » partout
            # serait faux sur l'amorçage. Le seul énoncé juste les nomme tous
            # les deux.
            st.caption(
                f"Modèle mûr à {maturity:.0%} : la moyenne de fond porte sur "
                f"{stats.CTL_DAYS} jours, l'historique n'en compte que "
                f"{len(full_daily)} de calendrier, dont "
                f"{quality.count_measured(full_daily)} mesurés. "
                "Le début de la courbe reste l'amorçage du modèle."
            )

# =============================================================================
# Repères chiffrés : où en est chaque métrique, et de combien elle a bougé
# DEPUIS LE DÉBUT DE L'HORIZON.
#
# Différence assumée avec les tuiles du Bilan : là-bas la pastille compare à la
# normale glissante sur 28 jours (« est-ce que ce jour est inhabituel ? »), ici
# au niveau du début de fenêtre (« d'où je viens ? »). Deux questions, deux
# références — et le libellé de chaque pastille dit laquelle.
# =============================================================================
# Références de départ calculées AVANT la carte, pour toutes les tuiles à la
# fois : la carte doit pouvoir dire en une ligne que le recul est plus court que
# l'horizon demandé. « 6 mois » en haut de page et « vs il y a 4 semaines » sous
# chaque pastille est exact des deux côtés (`long_term_reference` rabat sur le
# recul réellement disponible) et illisible ensemble — l'écart ne s'explique
# nulle part à l'écran.
#
# Recul compté depuis `as_of` et non depuis `end` : la fin de l'horizon peut
# tomber sur une journée écartée, et le recul annoncé serait alors d'un jour de
# plus que celui réellement parcouru.
requested_lag = (pd.Timestamp(as_of) - pd.Timestamp(start)).days
# Référence de DÉPART : médiane d'une quinzaine centrée sur le début de
# l'horizon, et non la valeur isolée de ce jour-là — comparer deux points uniques
# d'une série bruitée fabrique une tendance à partir de deux accidents.
references: dict[str, tuple[float | None, int]] = {
    key: stats.long_term_reference(
        _source(key), key, as_of, lag_days=requested_lag, half_window=7, min_lag_days=28,
    )
    for key, _label in TRACKED
}
# Le plus long recul réellement obtenu : c'est celui que les pastilles affichent.
achieved_lag = max((lag for prev, lag in references.values() if prev is not None),
                   default=0)


def _render_kpi(key: str) -> None:
    m = metric(key)
    src = _source(key)
    # Valeur LISSÉE, pas le point du jour.
    #
    # La page donnait deux réponses à « quelle est ma valeur ? » : la moyenne
    # 14 jours de la VO2max finissait à 52,3 sur le graphe, la tuile affichait le
    # dernier point quotidien, 54,2. Aucun des deux chiffres n'était faux ; c'est
    # d'en montrer deux qui l'était. Un point quotidien de VO2max est une
    # estimation démographique bruitée dont le registre dit lui-même de ne jamais
    # juger la variation d'un jour — le donner comme valeur de référence
    # contredisait sa propre notice.
    #
    # Même fenêtre que la courbe du graphe (`metric.ma_window`), pour que la
    # tuile et le trait épais disent le même nombre. Et même série pour la
    # sparkline, sinon son point terminal ne serait pas la valeur affichée.
    raw_series = src.set_index(pd.to_datetime(src["local_date"]))[key] \
        if key in src.columns and "local_date" in src.columns else pd.Series(dtype=float)
    series = raw_series.rolling(f"{m.ma_window}D",
                                min_periods=max(2, m.ma_window // 3)).mean() \
        if not raw_series.empty else raw_series
    valid = series.dropna()
    value = float(valid.iloc[-1]) if not valid.empty else None

    prev_value, real_lag = references[key]
    delta_label = f"vs il y a {real_lag // 30} mois" if prev_value is not None else ""
    if prev_value is not None and real_lag < 60:
        delta_label = f"vs il y a {round(real_lag / 7)} semaines"

    # Normale et z-score du MÊME calcul que sur le Bilan, pour que la couleur
    # d'une tuile ne dépende pas de la page où on la regarde.
    base_df, z_full = compute.baseline_and_z(src, key)
    z_last = z_full.iloc[-1] if len(z_full) and value is not None else None
    baseline_last, band_last = None, None
    valid_base = base_df.dropna(subset=["baseline"]) if "baseline" in base_df.columns else base_df
    if not valid_base.empty:
        baseline_last = float(valid_base["baseline"].iloc[-1])
        lo_b, hi_b = valid_base["lower"].iloc[-1], valid_base["upper"].iloc[-1]
        if pd.notna(lo_b) and pd.notna(hi_b):
            band_last = (float(lo_b), float(hi_b))

    charts.kpi_card(m, value, prev_value, series=series, z=z_last,
                    key=f"prog_{key}", delta_label=delta_label,
                    baseline=baseline_last, band=band_last)


with ui.card("Repères", info={
    "La pastille": "Elle compare la valeur actuelle au NIVEAU DE DÉPART de l'horizon "
                   "choisi, pas à ta normale sur 28 jours comme sur le Bilan : la "
                   "question ici est « d'où je viens ? ». Le libellé sous chaque "
                   "pastille dit le recul réellement utilisé, qui peut être plus court "
                   "que l'horizon demandé si l'historique ne va pas jusque-là.",
    "Pas de pastille": "Sous quatre semaines de recul, aucune comparaison n'est "
                       "affichée — un écart calculé sur dix jours et présenté comme une "
                       "évolution longue est un mensonge indétectable pour le lecteur.",
    "La sparkline": "La courbe couvre l'horizon choisi, la ligne pointillée est ta "
                    "normale glissante sur 28 jours et la bande grise ta fourchette "
                    "habituelle.",
    "Une valeur lissée": "Le chiffre affiché est la moyenne glissante, pas le point du "
                         "jour — la même que le trait épais des graphes, pour que la "
                         "tuile et la courbe ne donnent jamais deux réponses à « quelle "
                         "est ma valeur ? ». La fenêtre suit la métrique : quatorze jours "
                         "pour la VO2max, sept pour les autres. Ce n'est pas une "
                         "inégalité de traitement mais une différence de nature — la "
                         "VO2max est une estimation démographique dont un point isolé ne "
                         "veut rien dire, là où une fréquence de repos est une mesure "
                         "directe. Sept jours sur la VO2max laisseraient passer du bruit "
                         "pour de la progression.",
    "La date des valeurs": "Les quatre tuiles sont au MÊME jour, celui écrit sous le "
                           "titre : le dernier jour pleinement mesuré. Une journée dont "
                           "la couverture cardiaque tombe sous 80 % est écartée — sa FC "
                           "de repos et sa variabilité sont calculées sur quelques "
                           "heures. C'est pourquoi un chiffre peut différer de celui du "
                           "Bilan du jour, qui affiche la journée telle qu'elle est, "
                           "partielle comprise : ce ne sont pas deux mesures "
                           "contradictoires, ce sont deux jours.",
}):
    # La date sous le titre, pas dans une infobulle : sans elle, un écart avec
    # le Bilan se lit comme une contradiction entre deux pages. Et le recul
    # réellement utilisé au même endroit, quand il est plus court que l'horizon
    # demandé : le dire une fois pour la carte vaut mieux que de le laisser
    # deviner en comparant quatre libellés de pastille à l'en-tête de page.
    # Seuil PROPORTIONNEL et non absolu : une semaine de moins sur une fenêtre de
    # cinq n'est pas une nouvelle, la même semaine de moins sur une fenêtre de six
    # mois en est une. Sous 80 % du recul demandé, l'écart entre ce que l'en-tête
    # annonce et ce que les pastilles comparent devient visible, et doit se dire.
    clipped = achieved_lag and achieved_lag < requested_lag * 0.8
    limit = (f" · recul limité à {round(achieved_lag / 7)} semaines par "
             "l'historique disponible" if clipped else "")
    # L'ÉTENDUE en tête de légende, écrite en clair.
    #
    # Ces tuiles sont visuellement identiques à celles du Bilan mais répondent à
    # une autre question : « d'où je viens ? » contre « ce jour est-il
    # inhabituel ? ». Rien à l'écran ne distinguait les deux, et le lecteur qui
    # passe d'un onglet à l'autre lit la même grille avec des chiffres
    # différents. La plage de dates est le seul discriminant qui soit AUSSI une
    # information — une bordure ou un fond distinct auraient signalé la
    # différence sans jamais dire laquelle.
    span = (f"{common.format_fr_date(pd.Timestamp(start).date(), weekday=False, year=False)}"
            f" → {common.format_fr_date(as_of, weekday=False, year=False)}")
    st.markdown(
        f'<div class="bevel-card-caption">'
        f'<b style="color:{t["ink_primary"]}">{span}</b> · valeurs lissées'
        f"{', arrêtées au dernier jour pleinement mesuré' if as_of != hi_date else ''}"
        f"{limit}</div>",
        unsafe_allow_html=True,
    )
    ui.kpi_row([key for key, _ in TRACKED], _render_kpi, per_row=4)

ui.dismissed_summary()

# Le même pied que le Bilan, et c'est ICI qu'il compte le plus : tout sur cette
# page est régression, et c'est la profondeur d'historique qui décide de ce qui
# peut conclure.
common.page_footer(full_daily)

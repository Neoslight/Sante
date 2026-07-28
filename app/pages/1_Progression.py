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
#: Le même nom de domaine, indexé par clé — pour que les titres de graphe, les
#: nuances du verdict et le titre de carte disent tous le même mot.
LABELS: dict[str, str] = dict(TRACKED)

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

#: Hauteurs des graphes : DEUX valeurs, une par largeur de colonne.
#:
#: Une hauteur unique de 340 px écrasait les deux graphes en demi-largeur, dont
#: le rapport hauteur/largeur devenait presque carré là où leurs voisins pleine
#: largeur restaient panoramiques. Ce qui doit se conserver d'un graphe à l'autre
#: n'est pas la hauteur mais la proportion.
CHART_HEIGHT = 300
CHART_HEIGHT_HALF = 240

#: L'anatomie commune des graphes, dite UNE fois — les trois cartes en portaient
#: chacune une copie littérale, et une copie divergente est un mode d'emploi qui
#: décrit un dessin qui n'est plus là.
#:
#: Deux couches ont disparu du dessin depuis la version précédente de ce texte :
#: le pointillé de normale glissante (redondant avec la bande, qui est centrée
#: sur lui) et les segments entre mesures quotidiennes (une continuité jamais
#: mesurée). Les deux répondent maintenant au survol.
READ_CHART = (
    "Les points sont les mesures quotidiennes — un point, une journée, et un trou "
    "là où la journée a été écartée. Le trait épais est leur moyenne glissante, "
    "avec sa valeur écrite au bout. La bande teintée est ta zone normale sur "
    "28 jours : médiane glissante à plus ou moins un écart-type robuste, dont "
    "l'enveloppe est elle-même lissée sur une semaine — c'est un repère, pas une "
    "mesure, et sa dentelure au jour près serait du bruit. Elle s'éteint à ses "
    "deux bouts, là où l'historique ne suffit pas encore à la calculer. Survole "
    "pour la valeur exacte du jour, la normale et les bornes de la zone."
)

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
    start, end, missing_days = common.horizon_picker()

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

# Profondeur d'historique : UN SEUL énoncé, et annoncé uniquement s'il limite la
# lecture. Un badge « n=180 jours » confirmerait l'attendu et dépenserait de
# l'attention pour rien — même règle que le badge de qualité du Bilan.
#
# Le sélecteur d'horizon écrivait sa propre mention de profondeur juste à côté.
# Le lecteur recevait « 39 jours » puis « n=37 jours » en deux secondes sans
# savoir lequel comptait — et les deux étaient justes, l'un comptant le
# calendrier et l'autre les jours qui entrent réellement dans les régressions.
# C'est ce dernier qui compte ici, donc c'est lui qui reste ; ce que le
# sélecteur avait à dire devient une clause de ce badge.
n_measured = len(measured)
badge_text = stats.confidence_label(n_measured) if n_measured < 90 else ""
if missing_days:
    # En semaines restantes, pas en seuil : c'est la seule forme dont
    # l'utilisateur puisse faire quelque chose. Et sur l'horizon seulement —
    # une tendance, elle, est déjà décidable à partir de dix jours mesurés.
    weeks = max(1, round(missing_days / 7))
    clause = f"horizon réglable dans ~{weeks} semaine{'s' if weeks > 1 else ''} de mesures"
    badge_text = f"{badge_text} · {clause}" if badge_text else clause
if badge_text:
    st.markdown(
        f'<span class="bevel-badge">'
        f'<span class="bevel-badge-dot" style="background:{theme.active_tokens()["ink_muted"]}">'
        f"</span>{badge_text}</span>",
        unsafe_allow_html=True,
    )

def _source(key: str) -> pd.DataFrame:
    """Le CTL vient du modèle, les trois autres de mart.daily filtré.

    Le modèle, lui, produit une ligne par jour CALENDAIRE : il faut le recadrer
    sur `as_of`, sinon sa tuile devance d'un jour les trois autres.
    """
    if key != "ctl":
        return measured
    return ctl_window.loc[pd.to_datetime(ctl_window["local_date"]).dt.date <= as_of]


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
#: Série LISSÉE et valeur affichée, par métrique — calculées ici et non dans le
#: rendu des tuiles, parce que la carte « Progression » en a besoin AUSSI pour
#: son constat de fond de forme. Deux calculs pour la même phrase française
#: donnaient deux nombres : le constat disait « 35,0 → 28,5 » quand la tuile
#: affichait 28,8 et une variation de -6,4. Une seule référence par métrique et
#: par page, comme `compute.baseline_and_z` l'a imposé sur le Bilan.
SMOOTHED: dict[str, pd.Series] = {}
VALUES: dict[str, float | None] = {}
for _key, _label in TRACKED:
    _src = _source(_key)
    _raw = (_src.set_index(pd.to_datetime(_src["local_date"]))[_key]
            if _key in _src.columns and "local_date" in _src.columns
            else pd.Series(dtype=float))
    _w = metric(_key).ma_window
    _s = (_raw.rolling(f"{_w}D", min_periods=max(2, _w // 3)).mean()
          if not _raw.empty else _raw)
    SMOOTHED[_key] = _s
    _v = _s.dropna()
    VALUES[_key] = float(_v.iloc[-1]) if not _v.empty else None

# Le plus long recul réellement obtenu : c'est celui que les pastilles affichent.
achieved_lag = max((lag for prev, lag in references.values() if prev is not None),
                   default=0)

# =============================================================================
# Verdict de progression : UNE affirmation, ses nuances en dessous.
#
# Calque de la carte « Forme » du Bilan, et pour la même raison : quatre graphes
# empilés laissaient le lecteur composer lui-même la réponse à la question posée
# en titre, alors que le sens d'une pente n'est pas lisible sans le registre (une
# FC de repos qui baisse est une bonne nouvelle) ni sans son n.
# =============================================================================
t = theme.active_tokens()


trends = {
    label: (stats.trend(measured, key) if key in measured.columns else None,
            metric(key).direction)
    for key, label in TRACKED if key in VERDICT_KEYS
}
verdict = stats.progress_verdict(
    trends, primary=PRIMARY,
    units={label: metric(key).unit.rstrip() for key, label in TRACKED},
    # `missing_days` non nul = le sélecteur d'horizon n'a pas été rendu, faute
    # d'historique. Le conseil du verdict doit dépendre de la MÊME condition,
    # sinon la page retire le contrôle et souffle dans la même seconde
    # d'« élargir l'horizon ».
    can_widen=not missing_days,
)

#: Le sous-titre de tendance ne s'affiche QUE s'il distingue les graphes.
#:
#: « aucune tendance nette · historique encore court » apparaissait à l'identique
#: sous les trois graphes testés, et redisait ce que la carte de verdict venait
#: d'annoncer en haut de page — trois lignes de gris pour un seul bit
#: d'information déjà donné. C'est exactement la règle appliquée aux nuances par
#: `stats.merge_nuances` : tant que les métriques partagent le même statut, la
#: carte de verdict le porte seule. Le jour où l'une se détache, les lignes
#: réapparaissent, et c'est alors la RUPTURE DE MOTIF qui fait signal.
#:
#: Note recalculée exactement comme `metric_chart` la calcule (sur les lignes
#: non nulles de la métrique, pas sur `measured` entier) : une note prédite sur
#: un autre effectif pourrait basculer de palier de fiabilité et faire croire à
#: une différence là où il n'y en a pas.
def _note(key: str) -> str:
    sub = measured.dropna(subset=[key]) if key in measured.columns else measured.iloc[0:0]
    return charts.chart_note_text(stats.trend(sub, key) if len(sub) else None, len(sub))


SHOW_NOTE = len({_note(k) for k in VERDICT_KEYS}) > 1

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
    # Nuances FUSIONNÉES quand elles disent la même chose : trois lignes de
    # « aucune tendance nette » portent un seul bit d'information et occupent la
    # place de trois signaux (cf. `stats.merge_nuances`).
    nuance_html = ""
    for rank, (name, phrase, nst, _slope) in enumerate(
        stats.merge_nuances(verdict.nuances, span_days=n_measured)
    ):
        # Budget couleur identique au Bilan : seule la nuance dominante, et
        # seulement si elle demande une décision, porte sa couleur de statut.
        # Le glyphe neutre passe en encre EFFACÉE : à `ink_secondary`, il avait
        # le même poids que le texte et la ligne se lisait comme une entrée de
        # liste plutôt que comme une phrase.
        is_dominant = rank == 0 and nst in charts.ATTENTION_STATUSES
        glyph_color = charts.status_hex(nst, t) if is_dominant else t["ink_muted"]
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
    ctl_src = _source("ctl")
    m_ctl = metric("ctl")
    # LA MÊME référence que la tuile « Fond », au chiffre près.
    #
    # Le constat calculait son propre départ (valeur brute d'il y a 28 jours) et
    # la tuile le sien (médiane centrée de `long_term_reference`) : deux nombres
    # sous la même phrase française « sur 4 semaines », 28,5 ici et 28,8 là,
    # -6,5 contre -6,4. C'est la faute que `compute.baseline_and_z` a déjà
    # supprimée sur le Bilan — une seule référence par métrique et par page.
    was, real_days = references["ctl"]
    now = VALUES["ctl"]
    if was is not None and now is not None:
        span = (f"{round(real_days / 7)} dernières semaines" if real_days >= 10
                else f"{real_days} derniers jours")
        # Teinte d'IDENTITÉ du fond de forme, pas une couleur de statut : elle
        # dit de quelle courbe on parle, elle ne juge pas la baisse. Le budget
        # de statut de la page reste entier.
        ctl_hue = t["series"][m_ctl.palette_index % len(t["series"])]
        spark = charts.micro_sparkline(
            SMOOTHED["ctl"].tail(real_days + 1), ctl_hue, width=60, height=16,
        )
        aside_html = (
            f'<div class="bevel-verdict-aside">'
            f'<div class="bevel-verdict-aside-line">'
            f"<span>Fond de forme <b>{m_ctl.format(was)} → {m_ctl.format(now)}</b> "
            f"sur les {span}</span>"
            f'<span class="bevel-aside-delta" style="color:{ctl_hue}">'
            # Écart calculé sur les valeurs ARRONDIES, celles que le lecteur a
            # sous les yeux : sinon « 35,0 → 28,5 » s'accompagne d'un « −6,4 »
            # que personne ne peut refaire de tête.
            f"{m_ctl.format_delta(m_ctl.rounded(now) - m_ctl.rounded(was))}</span>"
            f'<span class="bevel-aside-spark">{spark}</span></div>'
            f"<i>Niveau, non testé — le fond de forme n'entre pas dans le verdict : "
            f"c'est une moyenne lissée, sa pente n'est pas testable.</i></div>"
        )
    # Corps du verdict indexé sur ce qu'il affirme : un statut neutre est par
    # définition une non-réponse, et l'écrire au corps réservé aux affirmations
    # d'état lui donnerait l'autorité d'une conclusion qu'elle refuse de tirer.
    soft = " bevel-verdict-soft" if verdict.status == "neutral" else ""
    st.markdown(
        f'<div class="bevel-verdict">'
        f'<div class="bevel-verdict-headline{soft}">{verdict.headline}</div>'
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
# Repères chiffrés : où en est chaque métrique, et de combien elle a bougé
# DEPUIS LE DÉBUT DE L'HORIZON.
#
# Différence assumée avec les tuiles du Bilan : là-bas la pastille compare à la
# normale glissante sur 28 jours (« est-ce que ce jour est inhabituel ? »), ici
# au niveau du début de fenêtre (« d'où je viens ? »). Deux questions, deux
# références — et le libellé de chaque pastille dit laquelle.
# =============================================================================


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
    series, value = SMOOTHED[key], VALUES[key]

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

# =============================================================================
# VO2max : la métrique de référence, seule dans sa carte
# =============================================================================
with ui.card("VO2max — la mesure de référence", info={
    "Ce que c'est": metric("vo2_max").how_read,
    "Lire le graphe": READ_CHART,
}):
    if "vo2_max" not in measured.columns or measured["vo2_max"].dropna().empty:
        ui.empty_state(
            "Pas d'estimation de VO2max sur cette fenêtre",
            hint="Fitbit ne l'estime qu'après des séances de course avec GPS.",
        )
    else:
        # `title=""` : la carte porte déjà « VO2max ». Le titre interne le
        # répétait et occupait la ligne où la note de tendance doit tenir.
        charts.metric_block(measured, metric("vo2_max"), title="",
                            show_trend=SHOW_NOTE, show_confidence=SHOW_NOTE,
                            height=CHART_HEIGHT)

# =============================================================================
# Les deux signaux courts, côte à côte : ils racontent la même histoire que la
# VO2max à une échelle de temps où elle ne bouge pas encore.
# =============================================================================
with ui.card("FC de repos & variabilité cardiaque", info={
    metric("resting_hr").short: f"{metric('resting_hr').what} {metric('resting_hr').how_read}",
    metric("hrv_rmssd").short: f"{metric('hrv_rmssd').what} {metric('hrv_rmssd').how_read}",
    "Lire le graphe": READ_CHART,
    "Pourquoi les deux ensemble": "Elles bougent en miroir : une FC de repos qui descend "
                                  "pendant que la variabilité monte est la signature d'une "
                                  "condition qui s'améliore. Quand elles divergent, c'est "
                                  "généralement le signe d'autre chose que l'entraînement "
                                  "(sommeil, alcool, maladie).",
}):
    # Les titres internes RESTENT — la carte nomme les deux métriques d'un seul
    # tenant, rien ne dirait laquelle est à gauche — mais ils prennent les noms
    # de DOMAINE de `TRACKED`, ceux du titre de carte et des nuances du verdict.
    #
    # Le registre dit « Fréquence cardiaque au repos » et « Variabilité cardiaque
    # (HRV) » : trois noms pour deux métriques tenaient dans deux centimètres de
    # hauteur. Un nom, un objet.
    # Hauteur explicite, et la MÊME que les graphes pleine largeur de la page :
    # laissée au défaut (320), elle donnait 340 sur la VO2max et le fond de forme
    # et 320 ici, soit deux hauteurs de graphe dans une même colonne de lecture.
    c1, c2 = st.columns(2)
    with c1:
        charts.metric_block(measured, metric("resting_hr"), title=LABELS["resting_hr"],
                            show_trend=SHOW_NOTE, show_confidence=SHOW_NOTE,
                            height=CHART_HEIGHT_HALF)
    with c2:
        charts.metric_block(measured, metric("hrv_rmssd"), title=LABELS["hrv_rmssd"],
                            show_trend=SHOW_NOTE, show_confidence=SHOW_NOTE,
                            height=CHART_HEIGHT_HALF)

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
    "Lire le graphe": READ_CHART,
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
        #
        # `show_y=False` : la carte dit elle-même que le fond de forme est en
        # unité arbitraire, « seuls comptent le SENS et l'ampleur relative du
        # déplacement, pas la valeur absolue ». Des graduations sous cette phrase
        # invitent à lire précisément ce qu'elle demande de ne pas lire — et le
        # Bilan applique déjà la règle sur la même grandeur.
        charts.metric_block(ctl_window, metric("ctl"), title="",
                            height=CHART_HEIGHT, warmup_until=warmup_until,
                            warmup_label="amorçage du modèle", show_y=False)
        # LE FAIT de la page, à la place de la mention technique.
        #
        # La courbe passe sous sa zone normale sur tout le dernier tiers de la
        # fenêtre et rien ne le disait ; la légende parlait à la place de maturité
        # du modèle — une propriété du CALCUL, désormais dessinée sur le graphe
        # (zone d'amorçage grisée, avec son filet). Le texte est libre pour ce que
        # le dessin ne dit pas : depuis quand.
        out = stats.outside_band_since(ctl_src, "ctl")
        if out is not None:
            since, way = out
            st.caption(
                f"{'Sous' if way < 0 else 'Au-dessus de'} ta zone normale depuis le "
                f"{common.format_fr_date(since, weekday=False, year=False)}."
            )

ui.dismissed_summary()

# Le même pied que le Bilan, et c'est ICI qu'il compte le plus : tout sur cette
# page est régression, et c'est la profondeur d'historique qui décide de ce qui
# peut conclure.
common.page_footer(full_daily)

"""Page « Aujourd'hui » : la seule question qui compte au réveil — je suis en
forme ou pas, et pourquoi ? Tout le reste (progression, entraînement,
récupération, dépense) a sa propre page ; celle-ci ne fait qu'agréger le
signal d'UN jour (choisi par l'utilisateur, par défaut le plus récent) et
dire s'il faut s'en inquiéter.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import datetime as dt

import pandas as pd
import streamlit as st

import charts
import common
import queries
import theme
import ui
import compute
from health import metrics as metrics_mod
from health import quality
from health import stats
from health.metrics import require as metric

st.set_page_config(page_title=common.PAGE_TITLE.format("Aujourd'hui"), layout="wide")
theme.inject_css()

# Le monogramme est désormais posé par `theme.inject_css()`, ci-dessus : Streamlit
# attache `st.logo` à la PAGE qui l'appelle, pas à l'application, et le garder ici
# le faisait disparaître sur toutes les autres pages.

# Pas de `st.title` : la page affiche le jour SÉLECTIONNÉ, pas forcément
# aujourd'hui. Un titre « Aujourd'hui » figé au-dessus d'une date au 19 juillet
# se contredit lui-même ; la date longue de l'en-tête tient déjà ce rôle.

full_daily = queries.daily()  # historique complet : le modèle CTL/ATL et les
# baselines personnelles ont besoin de tout le passé disponible, pas juste de
# la période affichée à l'écran.

if full_daily.empty:
    st.info("Pas encore de données ingérées.")
    st.stop()

# Dates du registre en `date` nu : `local_date` reste en datetime64 dans
# `full_daily` (les fonctions `stats.*` le re-convertissent elles-mêmes), une
# variable séparée sert aux comparaisons avec `selected_day`.
local_dates = pd.to_datetime(full_daily["local_date"]).dt.date

lo_ts, hi_ts = queries.date_bounds()
lo_date, hi_date = pd.Timestamp(lo_ts).date(), pd.Timestamp(hi_ts).date()

st.session_state.setdefault("selected_day", hi_date)
selected_day = min(max(st.session_state["selected_day"], lo_date), hi_date)
st.session_state["selected_day"] = selected_day

# =============================================================================
# En-tête : jour sélectionné, navigation, badge de qualité, bande de 14 jours
# =============================================================================
# Tableaux et formateur remontés dans `common` : la page « Progression » date
# désormais ses tuiles et allait recopier la liste des mois.
_WEEKDAYS_FR = common.WEEKDAYS_FR
_format_fr_date = common.format_fr_date


# =============================================================================
# Historique de référence et entrée du modèle de forme
#
# Placé AVANT l'en-tête parce que le badge de fiabilité en dépend : on ne peut
# pas avertir que le verdict repose sur une charge reconstruite sans savoir
# d'abord si elle l'est.
#
# Tout est calculé sur `history_upto` (jamais `full_daily`) : sinon regarder un
# jour passé afficherait une forme calculée avec des jours qui n'avaient pas
# encore eu lieu à ce moment-là.
# =============================================================================
history_upto = full_daily.loc[local_dates <= selected_day]

# Référence de normalité : jours réellement mesurés uniquement, le jour affiché
# excepté (cf. health/quality.reference_frame — il doit rester la dernière ligne
# du cadre pour que les `.iloc[-1]` visent bien ce jour-là).
history_ref = quality.reference_frame(history_upto, keep=selected_day)

# Entrée du modèle de forme : historique COMPLET, mais avec la charge des
# journées mal couvertes remplacée par la médiane glissante des journées
# mesurées.
#
# Sans ce traitement, le modèle lisait une charge sous-enregistrée comme une
# journée facile : le 25 juillet, 66 % de couverture et 15,2 de charge — soit
# exactement la médiane des jours pleins — passaient pour une vraie journée
# calme et gonflaient d'autant la fraîcheur affichée. Le badge ambre avertissait
# que les MESURES du jour étaient partielles ; il ne disait pas que le verdict
# en héritait.
#
# Retirer ces jours n'était pas une option : CTL et ATL sont des moyennes
# exponentielles à cadence quotidienne, un trou au milieu décalerait toute la
# décroissance.
model_input = quality.impute_partial_load(history_upto, load_col="cardio_load_total")

# Qualité de la donnée du jour choisi, depuis mart.daily (is_missing_day /
# is_partial_day / data_completeness). Lue AVANT l'en-tête : le badge de
# couverture se pose à côté de la date, là où la question se pose ("ce que je
# lis ci-dessous, c'est mesuré sur quoi ?"), et non dans une ligne méta où il
# était noyé avec la profondeur d'historique.
#
# Le badge n'apparaît QUE s'il y a un défaut à signaler. Une pastille verte
# « journée complète » est une alerte pour dire qu'il n'y a pas d'alerte : elle
# consomme une des deux couleurs du budget pour confirmer l'attendu.
t = theme.active_tokens()
day_row_df = full_daily.loc[local_dates == selected_day]
badge_color = badge_text = None
if day_row_df.empty:
    badge_color, badge_text = t["ink_muted"], "aucune donnée"
    row = None
else:
    row = day_row_df.iloc[0]
    if bool(row.get("is_missing_day", False)):
        badge_color, badge_text = t["ink_muted"], "aucune donnée"
    elif bool(row.get("is_partial_day", False)):
        completeness = row.get("data_completeness")
        # Espace insécable avant le %, comme le veut la typographie française —
        # et insécable pour que « 66 % » ne se coupe jamais en deux lignes.
        cov = f"{completeness * 100:.0f} %" if pd.notna(completeness) else "?"
        badge_color, badge_text = t["status"]["warning"], f"journée partielle · {cov} de couverture FC"

# Toutes les commandes de date dans UN seul groupe compact et centré : les
# flèches, la date, « Aujourd'hui », le calendrier. « Aujourd'hui » rejeté au
# bord de l'écran n'avait plus de lien visible avec la date qu'il déplace, et
# le calendrier en bout de bande de jours se lisait comme un quinzième jour.
# La bande, elle, reste le sélecteur principal — celui qu'on utilise sans
# réfléchir sur les deux dernières semaines.
with st.container(key="dayhead-nav"):
    # `vertical_alignment="center"` est l'alignement NATIF des colonnes
    # Streamlit : un bloc de texte de 15 px et un bouton de 32 px n'ont pas la
    # même hauteur de boîte, et aucune règle CSS posée sur les descendants ne
    # rattrape ça de façon fiable — c'est le conteneur de colonnes qui doit
    # aligner ses enfants.
    #
    # Largeurs INÉGALES : à cinq colonnes égales, chaque chevron occupait un
    # cinquième de la largeur de l'écran et la « barre compacte » visée était en
    # réalité étalée d'un bord à l'autre. Les flèches n'ont besoin que de la
    # place de leur icône ; c'est la date qui doit tenir le centre.
    nav_prev, nav_date, nav_next, nav_today, nav_pick = st.columns(
        [1, 5, 1, 2, 2], vertical_alignment="center",
    )
with nav_prev:
    # Icône vectorielle et non le caractère « ‹ » : ce glyphe est un guillemet
    # simple, dessiné haut dans le cadratin, si bien qu'il paraît décalé vers
    # le haut par rapport au texte qu'il encadre quel que soit l'alignement des
    # boîtes. L'icône, elle, est centrée par son propre conteneur.
    if st.button("", icon=":material/chevron_left:",
                 disabled=(selected_day <= lo_date), key="day-prev"):
        st.session_state["selected_day"] = max(lo_date, selected_day - dt.timedelta(days=1))
        st.rerun()
with nav_date:
    # Même ligne typographique que l'en-tête des pages de série
    # (`common.head_title_html`) : deux gabarits d'en-tête différents, une seule
    # définition du titre.
    st.markdown(common.head_title_html(_format_fr_date(selected_day)),
                unsafe_allow_html=True)
with nav_next:
    if st.button("", icon=":material/chevron_right:",
                 disabled=(selected_day >= hi_date), key="day-next"):
        st.session_state["selected_day"] = min(hi_date, selected_day + dt.timedelta(days=1))
        st.rerun()
with nav_today:
    if st.button("Aujourd'hui", disabled=(selected_day == hi_date), key="day-today"):
        st.session_state["selected_day"] = hi_date
        st.rerun()
with nav_pick:
    # Le calendrier revient dans la barre de date, avec les autres commandes de
    # date, et porte un libellé écrit. En bout de bande, il n'avait ni la place
    # d'un mot ni celle d'un pictogramme lisible, et se lisait comme un
    # quinzième jour.
    with st.popover("Choisir une date", width="stretch"):
        # Volontairement SANS `key` : un `st.date_input` à clé explicite garde
        # sa propre valeur en session et l'imposerait au rerun suivant, ce qui
        # annulerait aussitôt toute navigation faite par ‹ / › ou par la bande
        # de jours (le jour reviendrait à la dernière date choisie ici).
        picked = st.date_input(
            "Aller à…", value=selected_day, min_value=lo_date, max_value=hi_date,
        )
        if picked != selected_day:
            st.session_state["selected_day"] = picked
            st.rerun()

# Le badge SOUS la date, pas sur sa ligne : posé à côté du titre, il se lisait
# comme une précision de date. C'est un avertissement sur la fiabilité de tout
# ce qui suit, il doit se lire comme tel. Dans son propre conteneur, avec ses
# marges : posé en markdown nu, il se retrouvait à cheval sur la bande de jours
# qui le suit.
#
# La calibration de l'appareil s'ajoute ICI, comme second badge, et non en
# bandeau autonome plus bas : c'est une réserve sur la FIABILITÉ de ce que la
# page affiche, exactement comme la couverture partielle. Un bandeau à part,
# glissé entre la bande de jours et la carte Forme, en faisait un événement du
# jour — et contredisait la règle posée pour les conseils, qui vivent sous le
# verdict qu'ils précisent, jamais en bandeau autonome.
in_calibration = row is not None and (
    bool(row.get("readiness_in_calibration", False))
    or bool(row.get("cardio_load_in_calibration", False))
)
badges: list[tuple[str, str]] = []
if badge_text:
    badges.append((badge_color, badge_text))
if in_calibration:
    badges.append((t["status"]["warning"], "appareil en calibration · disponibilité et charge "
                                           "pas encore fiables"))
# Charge reconstruite dans la fenêtre de fatigue : le verdict en hérite.
#
# `quality.impute_partial_load` remplace la charge des journées mal couvertes,
# et c'est le bon traitement — mais une reconstruction silencieuse est
# indiscernable d'une mesure. Deux restrictions, pour que ce badge reste rare :
#
# * seulement dans les 7 jours qui pèsent réellement sur la fatigue du jour
#   affiché — au-delà, la moyenne exponentielle a tout amorti et l'annoncer
#   mettrait un avertissement permanent à l'écran ;
# * jamais pour le jour affiché LUI-MÊME : sa couverture partielle est déjà
#   dite par le badge juste à côté, et deux badges ambre pour une seule cause
#   dépensent le budget couleur à répéter la même chose.
#
# Ce qui reste est exactement l'information que rien d'autre ne porte : « un
# AUTRE jour de la semaine écoulée a une charge reconstruite ».
_atl_dates = pd.to_datetime(model_input["local_date"]).dt.date
_atl_window = model_input.loc[
    (_atl_dates > selected_day - dt.timedelta(days=stats.ATL_DAYS))
    & (_atl_dates != selected_day)
]
n_imputed = int(_atl_window.get("load_imputed", pd.Series(dtype=bool)).sum())
if n_imputed:
    badges.append((
        t["status"]["warning"],
        f"charge reconstruite sur {n_imputed} jour{'s' if n_imputed > 1 else ''} "
        "de la dernière semaine · verdict indicatif",
    ))
if badges:
    with st.container(key="dayhead-badge"):
        st.markdown(
            "".join(
                f'<span class="bevel-badge">'
                f'<span class="bevel-badge-dot" style="background:{color}"></span>'
                f"{text}</span>"
                for color, text in badges
            ),
            unsafe_allow_html=True,
        )

# =============================================================================
# Modèle de forme (calculé ici) — cf. health/stats.ctl_atl_tsb
# =============================================================================
ctl_df = stats.ctl_atl_tsb(model_input, load_col="cardio_load_total")
ctl_dates = pd.to_datetime(ctl_df["local_date"]).dt.date
last_ctl_rows = ctl_df.loc[ctl_dates == selected_day]
last_ctl = last_ctl_rows.iloc[0] if not last_ctl_rows.empty else None

# Bande des 14 derniers jours jusqu'au jour sélectionné.
#
# Les pastilles ne portent PLUS le statut de forme de chaque jour : quatorze
# pastilles colorées, c'est quatorze objets qui réclament l'attention pour une
# information que la courbe fond/fatigue donne désormais en continu, sur 28
# jours et avec ses valeurs. Ne reste que ce qu'une courbe ne dit pas : ce
# jour-là, y a-t-il eu une mesure ? Pastille pleine oui, creuse non.
strip_start = max(lo_date, selected_day - dt.timedelta(days=13))
strip_days = [strip_start + dt.timedelta(days=i) for i in range((selected_day - strip_start).days + 1)]
# Pas de zéro initial : « 02 » ne s'écrit pas en français, et l'alignement
# des numéros vient de la largeur égale des colonnes, pas du remplissage.
strip_labels = [str(sd.day) for sd in strip_days]
strip_colors: list[str | None] = []
for sd in strip_days:
    day_rows = full_daily.loc[local_dates == sd]
    has_data = not day_rows.empty and not bool(day_rows.iloc[0].get("is_missing_day", False))
    strip_colors.append(t["ink_muted"] if has_data else None)

strip_weekdays = [_WEEKDAYS_FR[sd.weekday()][0].upper() for sd in strip_days]
# Pas de ligne de mois : le mois est déjà écrit en toutes lettres dans la date
# juste au-dessus. Un repère qui répète l'information voisine ne repère rien.
clicked_day = ui.day_strip(
    strip_days, strip_labels, strip_colors, selected_day,
    weekday_labels=strip_weekdays, today=hi_date,
)
if clicked_day is not None and clicked_day != selected_day:
    st.session_state["selected_day"] = clicked_day
    st.rerun()

#: Seuil d'ALERTE sur la dérive de FC de repos, en sigmas robustes — la mesure,
#: elle, vit dans `stats.resting_hr_drift`. 1,5 sigma : au-dessus du seuil de
#: « notable » employé pour les nuances du verdict (1 sigma), parce qu'une
#: alerte appelle une action et doit rester rare. Sur cet historique, sigma vaut
#: ~2,6 bpm — le seuil tombe donc vers 4 bpm.
RHR_ALERT_SIGMA = 1.5


def _day_advice(day_row, history: pd.DataFrame) -> list[tuple[str, str]]:
    """Conseils chiffrés du jour : (texte, identifiant de bandeau).

    Deux règles seulement, et toutes deux actionnables : le ratio de charge
    aigu/chronique hors de sa plage soutenable, et une FC de repos qui dérive.
    Liste VIDE quand il n'y a rien à dire -- l'appelant n'affiche alors rien du
    tout. Un bandeau « Rien à signaler » est une alerte pour dire qu'il n'y a
    pas d'alerte : il occupe la place et la charge visuelle d'un signal, tout
    en n'en portant aucun.
    """
    out: list[tuple[str, str]] = []
    if day_row is not None:
        lo_acwr, hi_acwr = metric("acwr_ratio").good_range
        last_acwr = day_row.get("acwr_ratio")
        if pd.notna(last_acwr):
            if last_acwr < lo_acwr:
                out.append((
                    f"Volume en retrait (ACWR {last_acwr:.2f}, sous {lo_acwr}) : tu peux remonter "
                    "le volume progressivement cette semaine, la marge est là.",
                    f"acwr-low-{last_acwr:.2f}",
                ))
            elif last_acwr > hi_acwr:
                out.append((
                    f"Volume en hausse rapide (ACWR {last_acwr:.2f}, au-dessus de {hi_acwr}) : "
                    "ajoute un jour de repos ou allège la prochaine séance avant de continuer à monter.",
                    f"acwr-high-{last_acwr:.2f}",
                ))

    # FC de repos : la MESURE vient de `stats.resting_hr_drift` (fenêtres
    # glissantes des deux côtés, écart en sigmas robustes), le SEUIL et la
    # phrase restent ici — c'est la page qui décide à partir de quand elle
    # dérange le lecteur.
    rhr_series = history["resting_hr"] if "resting_hr" in history.columns else pd.Series(dtype=float)
    drift = stats.resting_hr_drift(rhr_series)
    if drift is not None:
        recent, base, sigmas = drift
        if sigmas > RHR_ALERT_SIGMA:
            out.append((
                f"FC de repos en hausse ({recent:.0f} vs {base:.0f} bpm sur les "
                f"{stats.RHR_REF_DAYS} jours précédents, soit {sigmas:.1f} écarts-types) : "
                "privilégie une charge légère et surveille ton sommeil les prochains jours.",
                f"rhr-{recent:.0f}-{base:.0f}",
            ))
    return out


# =============================================================================
# Fenêtre des SPARKLINES : longueur héritée du sélecteur de la sidebar
# (common.date_range_picker, inchangé), mais REBASÉE sur le jour choisi --
# sinon changer de jour dans l'en-tête n'aurait aucun effet sur les tuiles.
#
# Cette fenêtre ne sert plus qu'à tracer la courbe et ses bornes min/max. La
# période précédente qu'on chargeait ici pour alimenter les pastilles n'a plus
# d'objet : la pastille compare désormais à la normale glissante, la seule
# référence de la tuile.
# =============================================================================
# « Fenêtre des tuiles » et non « Fenêtre de comparaison » : ce sélecteur ne
# gouverne QUE la longueur des sparklines et de leurs bornes min/max. Ni le
# verdict, ni la courbe fond/fatigue, ni les normales 28 j n'en dépendent —
# et ne doivent pas en dépendre : une courbe fond/fatigue réduite à sept jours
# ne montrerait plus rien de ce qu'elle existe pour montrer, et une normale
# dont la fenêtre change avec un menu n'est plus une normale.
sidebar_start, sidebar_end = common.date_range_picker("Fenêtre des tuiles")
n_days = (pd.Timestamp(sidebar_end) - pd.Timestamp(sidebar_start)).days + 1
win_end = selected_day
win_start = win_end - dt.timedelta(days=n_days - 1)
d = queries.daily(str(win_start), str(win_end))

# =============================================================================
# Verdict du jour : UNE seule affirmation d'état, ses nuances en dessous.
#
# Cette carte remplace les deux qui se contredisaient (« Forme » disait
# « Frais », « Signaux du jour » disait « récupération en dessous »). Le verdict
# vient de `stats.day_verdict`, seul point de décision : la page ne fait plus
# que le rendre.
# =============================================================================
# z-scores position-alignés sur la DERNIÈRE ligne de leur DataFrame d'entrée
# (comportement de `stats.robust_z`, qui renvoie une série à index positionnel
# propre, pas l'index d'origine) : `ctl_df` et `history_upto` se terminent tous
# deux au jour sélectionné dès lors qu'il existe, donc `.iloc[-1]` cible bien
# CE jour-là. Jour absent de mart.daily -> aucun signal, plutôt que les
# z-scores d'un autre jour sous le libellé du jour affiché.
def _last_z(df: pd.DataFrame, col: str) -> float | None:
    if row is None or col not in df.columns:
        return None
    # Sans `date_col` explicite : la valeur par défaut de `stats.robust_z` est
    # déjà "local_date", et deux styles d'appel pour le même calcul finissent
    # toujours par diverger — le jour où la nuance du verdict et la couleur
    # d'une tuile se contrediraient, personne ne chercherait ici.
    z = stats.robust_z(df, col)
    return float(z.iloc[-1]) if len(z) and pd.notna(z.iloc[-1]) else None


# Noms de DOMAINE, sans la métrique entre parenthèses : ils entrent tels quels
# dans la phrase du verdict (« Frais, mais récupération en retrait »), où
# « récupération (HRV) » ferait trébucher la lecture. Ce que chacun mesure est
# dit une fois, dans le « ? » de la carte.
signal_defs = [
    ("Fatigue", _last_z(ctl_df, "atl"), metric("atl").direction),
    ("Récupération", _last_z(history_ref, "hrv_rmssd"), metric("hrv_rmssd").direction),
    ("Sommeil", _last_z(history_ref, "sleep_minutes_asleep"),
     metric("sleep_minutes_asleep").direction),
]
tsb_val = last_ctl["tsb"] if last_ctl is not None else None
ctl_val = last_ctl["ctl"] if last_ctl is not None else None
verdict = stats.day_verdict(tsb_val, ctl_val, {n: (z, d_) for n, z, d_ in signal_defs})

with ui.card("Forme", info={
    "Le verdict": metric("tsb").how_read,
    "Les nuances": "Trois domaines, comparés à TA normale des 28 derniers jours et non à "
                   "une valeur de référence générique : fatigue récente (moyenne de charge "
                   "sur 7 jours), récupération (variabilité cardiaque de la nuit), sommeil "
                   "(durée réellement endormie). Seuls les écarts d'au moins un écart-type "
                   "sont affichés : en deçà, il n'y a rien à dire.",
    "La réglette": "Elle situe la forme du jour sur son échelle, graduée en pourcentage "
                   "de ton fond. Le point plein est aujourd'hui, le point creux (marqué "
                   "« il y a 7 j ») ta position d'il y a une semaine — c'est le sens du "
                   "déplacement qui compte, plus que la valeur isolée. Les bornes ne "
                   "dépendent QUE de ton fond, jamais de la valeur du jour : elles ne "
                   "bougent donc pas quand tu navigues d'un jour à l'autre, et les deux "
                   "points sont bien sur la même règle. Une valeur qui sortirait de "
                   "l'échelle se pose au bout plutôt que de l'étirer.",
    "Fond et fatigue": "Les deux moyennes de la charge du jour (la tuile « Charge » plus "
                       "bas) : le fond sur 42 jours, en bleu, est la capacité construite ; "
                       "la fatigue sur 7 jours, en orange, est ce qu'elle coûte en ce "
                       "moment. La forme est leur différence. L'échelle verticale est en "
                       "unité arbitraire de charge cardio — seuls comptent les écarts et "
                       "les tendances, pas les valeurs absolues, d'où l'absence de "
                       "graduations.",
    "La bande de jours": "Sous chaque numéro, une pastille pleine signale un jour "
                         "réellement mesuré et une pastille creuse un jour sans donnée — "
                         "elle ne code aucun état du corps, l'état des jours passés se lit "
                         "sur la courbe ci-dessus. Le jour affiché a le fond vert, "
                         "aujourd'hui un simple contour vert.",
    "Le bandeau ambre": "Il n'apparaît que si la journée est mal couverte : sous 80 % "
                        "d'échantillons de fréquence cardiaque, elle est marquée partielle "
                        "et exclue des moyennes. Le pourcentage indiqué est cette "
                        "couverture. L'ambre ne dit jamais rien de ton état — seulement "
                        "de la fiabilité de ce qui est affiché.",
}):
    if last_ctl is None:
        ui.empty_state(
            "Pas de forme calculable pour ce jour",
            hint="Le modèle CTL/ATL n'a pas encore atteint ce jour dans l'historique.",
        )
    else:
        # LE VERDICT D'ABORD, en haut à gauche. Il était à droite d'une jauge
        # qui occupait le coin de lecture — la position la plus forte de la
        # carte allait au dispositif, pas à l'information. Le score le suit sur
        # la même ligne et à la même taille : c'est le chiffre du verdict, il
        # n'a rien à faire en gris pâle et en petit.
        verdict_color = charts.status_hex(verdict.status, t)
        tsb_txt = f"{tsb_val:+.0f}" if pd.notna(tsb_val) else "—"
        nuance_html = ""
        for rank, (name, phrase, nst, _z) in enumerate(verdict.nuances):
            # Budget couleur : le curseur de la réglette et la nuance dominante.
            # Les nuances suivantes passent en encre — leur glyphe dit déjà le
            # sens, leur phrase dit déjà le niveau.
            is_dominant = rank == 0 and nst in charts.ATTENTION_STATUSES
            glyph_color = charts.status_hex(nst, t) if is_dominant else t["ink_secondary"]
            nuance_html += (
                f'<div class="bevel-nuance">'
                f'<span class="bevel-flag" style="color:{glyph_color}" '
                f'title="{charts.STATUS_LABELS[nst]}">{charts.STATUS_GLYPHS[nst]}</span>'
                f"<span>{name} — {phrase}</span></div>"
            )
        st.markdown(
            f'<div class="bevel-verdict">'
            f'<div class="bevel-verdict-headline">{verdict.headline}'
            f'<span class="bevel-verdict-score">{tsb_txt}</span></div>'
            f'<div class="bevel-verdict-hint">{verdict.hint}</div>'
            f"{nuance_html}</div>",
            unsafe_allow_html=True,
        )

        # Réglette plutôt que demi-cercle : la position se lit de gauche à
        # droite, chaque zone porte son nom sous elle, et le repère fantôme
        # répond à « par rapport à avant ? » — ce que la jauge ne disait pas.
        week_ago_rows = ctl_df.loc[ctl_dates == selected_day - dt.timedelta(days=7)]
        st.markdown(
            charts.form_rail(
                tsb_val, stats.tsb_rail_ranges(tsb_val, ctl_val, metric("tsb").good_range),
                previous=float(week_ago_rows.iloc[0]["tsb"]) if not week_ago_rows.empty else None,
                zone_labels={k: stats.TSB_BADGES[k][0] for k in
                             ("critical", "serious", "good", "excellent")},
            ),
            unsafe_allow_html=True,
        )

        # La courbe qui manquait : le verdict est une différence entre deux
        # moyennes mobiles, et aucune des deux n'était visible. Ses valeurs
        # sont écrites au bout de chaque ligne, ce qui rend inutiles la légende
        # du haut ET la ligne « Fond (CTL) 28,2 · Fatigue (ATL) 20,3 » qui
        # traînait en bas de carte.
        st.plotly_chart(charts.form_trend(ctl_df, selected=selected_day), width="stretch")

        # Conseils chiffrés (volume en retrait ou en hausse rapide, FC de repos
        # qui dérive) : ils vivent SOUS le verdict qu'ils précisent, jamais en
        # bandeau autonome plus bas dans la page.
        #
        # `info` (neutre) et non `warning` : l'ambre est réservée à la qualité
        # de la donnée. Un conseil de volume n'est pas un défaut de mesure.
        for text, msg_id in _day_advice(row, history_ref):
            ui.notice(text, kind="info", msg_id=msg_id)

        with st.expander("Détail chiffré"):
            st.write(
                f"**Fond (CTL) : {metric('ctl').format(ctl_val)}** · "
                f"**Fatigue (ATL) : {metric('atl').format(last_ctl['atl'])}** · "
                f"forme = fond − fatigue = {metric('tsb').format(tsb_val)}"
            )
            for name, z, _direction in signal_defs:
                st.write(f"**{name}** · {f'z = {z:+.1f}' if z is not None else '—'}")
            readiness_val = row.get("readiness_score") if row is not None else None
            if readiness_val is not None and pd.notna(readiness_val):
                st.write(
                    f"**{metric('readiness_score').short}** (Fitbit) · "
                    f"{metric('readiness_score').format(float(readiness_val))} — "
                    "score propriétaire non reproductible, donné ici comme point de "
                    "comparaison externe, pas comme verdict."
                )
            st.caption(
                "z-score robuste : écart à ta médiane des 28 derniers jours, exprimé en "
                "écarts-types. 0 = ta normale, ±1 = un écart notable, ±2 = inhabituel."
            )
            ctl_maturity = float(last_ctl["ctl_maturity"])
            if ctl_maturity < 1.0:
                st.caption(
                    f"Modèle mûr à {ctl_maturity:.0%} : la moyenne de fond se calcule sur "
                    f"{stats.CTL_DAYS} jours, l'historique n'en compte que "
                    f"{len(history_upto)} à cette date. La valeur reste indicative."
                )

# =============================================================================
# KPIs du jour, avec sparkline sur la fenêtre rebasée sur le jour sélectionné
# =============================================================================
# Huit tuiles pleines en 4x2, en DEUX groupes de sens : la grille s'arrêtait à
# sept et laissait un trou sous « FC repos », et son ordre mêlait ce que la
# journée a demandé au corps et ce que le corps en dit. Ce sont deux questions
# différentes, elles se lisent maintenant sur deux lignes différentes.
#
# `readiness_score` reste dehors — c'était un troisième score d'état concurrent
# du verdict ; il est consultable dans « Détail chiffré ».
KPI_GROUPS: list[tuple[str, list[str]]] = [
    ("Activité", ["steps", "calories_total", "azm_points_total", "cardio_load_total"]),
    ("Récupération & fond", ["sleep_minutes_asleep", "resting_hr", "hrv_rmssd", "vo2_max"]),
]
# Métriques à variation LENTE : leur comparer une moyenne sur la fenêtre
# affichée ne produit que du bruit d'estimation. La VO2max bouge de quelques
# dixièmes par mois ; un « +0,1 vs moyenne 28 j » n'est pas une nouvelle, c'est
# l'incertitude de l'estimation démographique. Trois mois est la plus courte
# fenêtre où sa variation soit lisible.
#
# La référence est la MÉDIANE d'une quinzaine centrée sur le jour d'il y a
# 90 jours, et non sa valeur isolée : comparer deux points uniques d'une série
# bruitée fabriquerait une tendance à partir de deux accidents.
SLOW_METRICS: dict[str, tuple[int, int]] = {"vo2_max": (90, 7)}
#: Sous ce recul, il n'y a pas de tendance longue à annoncer — seulement du
#: bruit d'estimation étalé sur quelques semaines.
SLOW_MIN_LAG_DAYS = 28


def _slow_label(lag_days: int) -> str:
    """Recul en clair — la seule part de la comparaison longue qui relève de la
    page. Le calcul, lui, vit dans `stats.long_term_reference`."""
    return f"sur {lag_days // 30} mois" if lag_days >= 60 else f"sur {round(lag_days / 7)} semaines"


def _render_kpi(key: str) -> None:
    m = metric(key)
    series_period = d[key] if key in d.columns else pd.Series(dtype=float)
    # La valeur affichée est celle DU JOUR sélectionné, lue sur sa ligne de
    # mart.daily -- pas la dernière valeur non nulle de la fenêtre : sur un
    # jour sans mesure, cette dernière afficherait le chiffre d'un autre jour
    # sous le libellé du jour choisi. Pas de mesure -> "—", et pas de statut.
    raw = row.get(key) if row is not None else None
    value = float(raw) if raw is not None and pd.notna(raw) else None
    # Normale et z-score EN UN SEUL CALCUL, sur `history_ref` et jamais
    # `full_daily` : même règle « pas de futur » que le modèle de forme — un
    # jour passé ne doit pas être jugé à l'aune de jours qui n'avaient pas
    # encore eu lieu.
    #
    # `compute.baseline_and_z` garantit en outre que les deux sortent de la MÊME
    # médiane glissante : c'est ce qui rend impossible qu'une tuile annonce une
    # hausse au-dessus d'un point situé sous son pointillé. Auparavant, chaque
    # tuile calculait cette médiane deux fois — seize fois par grille — et
    # jetait la moitié du travail.
    base_df, z_full = compute.baseline_and_z(history_ref, key)
    z_last = None
    if value is not None and len(z_full):
        z_last = z_full.iloc[-1]
    baseline_last, band_last = None, None
    valid_base = base_df.dropna(subset=["baseline"]) if "baseline" in base_df.columns else base_df
    if not valid_base.empty:
        baseline_last = float(valid_base["baseline"].iloc[-1])
        lo_b, hi_b = valid_base["lower"].iloc[-1], valid_base["upper"].iloc[-1]
        # Fourchette habituelle (± 1 sigma robuste) dessinée derrière la
        # courbe : sans repère d'amplitude, l'échelle automatique rend une
        # métrique stable aussi agitée qu'une métrique qui double.
        if pd.notna(lo_b) and pd.notna(hi_b):
            band_last = (float(lo_b), float(hi_b))
    # UNE SEULE normale par tuile — celle du pointillé, celle du z-score, celle
    # de la pastille.
    #
    # La pastille comparait jusqu'ici à la moyenne des `n_days` jours précédant
    # la fenêtre, quand le pointillé traçait la médiane glissante sur 28 jours
    # au jour affiché. Deux références au calcul différent sous le même mot,
    # « moyenne » : il suffisait d'un jour un peu inhabituel pour que la
    # pastille annonce « +9 » au-dessus d'un point visiblement SOUS le
    # pointillé, sans que rien à l'écran ne permette de comprendre pourquoi.
    #
    # Une seule référence rend la contradiction impossible par construction, et
    # le libellé peut enfin nommer ce à quoi il compare.
    prev_value = baseline_last
    delta_label = "vs ta normale 28 j"
    slow = SLOW_METRICS.get(key)
    if slow is not None:
        lag_days, half_window = slow
        prev_value, real_lag = stats.long_term_reference(
            history_ref, key, selected_day, lag_days, half_window, SLOW_MIN_LAG_DAYS,
        )
        # Pas assez de recul : aucune comparaison plutôt qu'une comparaison
        # courte déguisée en tendance longue.
        delta_label = _slow_label(real_lag) if prev_value is not None else ""
    charts.kpi_card(m, value, prev_value, series=series_period, z=z_last,
                    key=f"kpi_{key}", delta_label=delta_label,
                    baseline=baseline_last, band=band_last)


with ui.card("Le jour en chiffres", info={
    metric(k).short: f"{metric(k).what} {metric(k).how_read}"
    for _, keys in KPI_GROUPS for k in keys
} | {
    "Lire une tuile": "La pastille, la ligne pointillée et la couleur reposent toutes "
                      "les trois sur la MÊME référence : ta normale sur 28 jours, la "
                      "médiane glissante des jours réellement mesurés. La pastille ne "
                      "peut donc pas annoncer une hausse au-dessus d'un point situé "
                      "sous le pointillé. C'est un fait, pas un jugement, donc grise. "
                      "Deux métriques font exception et se colorent quand "
                      "elles reculent : la variabilité cardiaque et la fréquence de repos "
                      "sont les seules dont un retard dise quelque chose du corps quel "
                      "qu'ait été le programme de la journée. La VO2max, elle, bouge trop "
                      "lentement pour qu'une comparaison quotidienne ait un sens : sa "
                      "pastille la compare à son niveau d'il y a trois mois, ou au plus "
                      "ancien que l'historique permette — la pastille dit alors le recul "
                      "réellement utilisé.",
    "Lire une sparkline": "Le point plein marque le jour affiché, la ligne pointillée ta "
                          "normale sur 28 jours, la bande grise ta fourchette habituelle. "
                          "Les deux nombres sous la courbe sont le minimum et le maximum "
                          "de la fenêtre affichée. Survole une tuile pour colorer sa "
                          "courbe : c'est la teinte que porte cette métrique dans les "
                          "graphes des autres pages.",
}):
    # Deux groupes, pas huit tuiles en vrac : l'ordre précédent alternait effort
    # et récupération, si bien que deux tuiles voisines n'avaient aucune raison
    # d'être voisines. Un intitulé en capitales suffit à séparer — un filet de
    # plus dans une carte déjà bordée n'apporterait que du trait.
    for rank, (group_label, keys) in enumerate(KPI_GROUPS):
        # La légende du pointillé se pose au bout de la PREMIÈRE ligne
        # d'intitulé, pas sous la première tuile : sous la tuile, elle lui
        # ajoutait une ligne qu'aucune de ses trois voisines n'avait, et
        # décalait le bas de toute la rangée pour légender huit courbes depuis
        # un coin. Ici, elle est sur la ligne qui couvre les quatre.
        note = ('<span class="bevel-group-note"><i></i>moyenne 28 j</span>'
                if rank == 0 else "")
        st.markdown(
            f'<div class="bevel-group{" bevel-group-gap" if rank else ""}">'
            f"<span>{group_label}</span>{note}</div>",
            unsafe_allow_html=True,
        )
        ui.kpi_row(keys, _render_kpi, per_row=4)

# =============================================================================
# Temps en effort : combien de minutes la journée a réellement demandé un
# effort, et à quelle intensité.
#
# La zone « légère » de Fitbit est VOLONTAIREMENT exclue : sa borne basse est à
# 30 bpm (cf. mart.hr_zones), si bien qu'elle contient toute minute où le cœur
# bat -- soit ~1 400 minutes par jour, la journée entière. Un « temps en zone :
# 15 h 48 » ne mesurait donc pas l'effort, il mesurait le port de la montre. Ne
# restent ici que les trois zones qui demandent quelque chose au système
# cardiovasculaire.
#
# Ce sont des MINUTES mesurées (raw.time_in_heart_rate_zone), pas de la charge :
# la charge du jour, score propriétaire, garde sa tuile dans la grille ci-dessus.
# =============================================================================
_EFFORT_ZONES = [
    ("Modérée", "hr_zone_moderate_min"),
    ("Soutenue", "hr_zone_vigorous_min"),
    ("Pic", "hr_zone_peak_min"),
]
_EFFORT_COLS = [col for _, col in _EFFORT_ZONES]


def _light_zone_ceiling(day_row) -> float | None:
    """Borne haute de la zone légère du jour, en bpm : le seuil à partir duquel
    une minute compte comme un effort. Lue dans mart.hr_zones, qui la recalcule
    chaque jour -- l'écrire en dur la figerait à la condition d'un moment."""
    if day_row is None:
        return None
    zones = queries.hr_zones(str(selected_day))
    light = zones.loc[zones["heart_rate_zone_type"] == "LIGHT"] if not zones.empty else zones
    return float(light.iloc[0]["max_bpm"]) if not light.empty else None


with ui.card("Temps en effort", info={
    "Ce que c'est": "Le nombre de minutes de la journée passées au-dessus de la zone "
                    "légère, réparties par intensité, d'après tes bornes personnelles "
                    "recalculées chaque jour par l'appareil.",
    "Pourquoi la zone légère n'y est pas": "Sa borne basse est à 30 battements par "
                                           "minute : elle contient donc toute minute où "
                                           "le cœur bat, soit la journée entière. La "
                                           "compter donnait un « temps en zone » de plus "
                                           "de 15 heures, qui mesurait le port de la "
                                           "montre et non l'effort.",
    "Où passe exactement le seuil": "Au bas de la zone modérée, une borne que l'appareil "
                                    "recalcule chaque jour à partir de ta fréquence de "
                                    "repos — sa valeur du jour est écrite sous le titre. "
                                    "Elle tombe autour de 40 % de ta réserve cardiaque, "
                                    "l'écart entre ton repos et ton maximum théorique : "
                                    "c'est un seuil d'effort réel, marcher vite y suffit, "
                                    "être assis non.",
    "Comment le lire": "Ce sont des minutes mesurées, pas un score — la charge du jour, "
                       "elle, est un indice propriétaire et vit dans sa propre tuile. "
                       "La barre fine sous la barre du jour est ta répartition MOYENNE "
                       "sur 28 jours, tracée sur le même axe : c'est elle qui dit si la "
                       "journée est ordinaire. L'espace gris à droite va jusqu'à ton "
                       "maximum déjà observé.",
}):
    zone_values = [
        (label, float(row[col]))
        for label, col in _EFFORT_ZONES
        if row is not None and col in row.index and pd.notna(row[col])
    ]
    if not zone_values or sum(v for _, v in zone_values) == 0:
        # « aujourd'hui » seulement quand c'est vrai : la page navigue dans le
        # passé, et l'affirmer sur le 20 juillet serait faux tous les autres
        # jours de l'année.
        ui.empty_state(
            "Aucune activité soutenue "
            + ("aujourd'hui" if selected_day == hi_date else "ce jour-là"),
            hint="La fréquence cardiaque n'a pas dépassé la zone légère de la journée.",
        )
    else:
        total_min = sum(v for _, v in zone_values)
        ceiling_bpm = _light_zone_ceiling(row)
        # Le titre de la carte dit déjà « Temps en effort » : la légende n'a
        # qu'à donner le chiffre et le seuil qui le définit.
        seuil = f" au-dessus de {ceiling_bpm:.0f} bpm" if ceiling_bpm else ""
        st.markdown(
            f'<div class="bevel-card-caption">'
            f'<b style="color:{t["ink_primary"]}">{metrics_mod.format_duration(total_min)}</b>'
            f"{seuil}</div>",
            unsafe_allow_html=True,
        )
        # Deux références, toutes deux tirées de l'historique connu À CETTE DATE
        # (jamais `full_daily`) et des seules journées RÉELLEMENT MESURÉES.
        #
        # Le `fillna(0)` sur l'historique brut transformait chaque journée sans
        # montre en journée à zéro minute d'effort. Quelques jours non portés
        # suffisaient alors à tirer la moyenne de référence vers le bas — et
        # donc à faire passer une journée ordinaire pour une bonne journée,
        # exactement l'erreur que cette barre de comparaison existe pour éviter.
        # `quality.reference_frame` les écarte ; le `fillna(0)` qui reste ne
        # comble plus que les zones vides d'un jour bien mesuré, un vrai zéro.
        # Sans `keep=` ici, contrairement aux normales : la barre de référence
        # n'a aucune raison de conserver un jour partiel, elle n'existe que pour
        # dire ce qu'est une journée ordinaire.
        effort_cols = [c for c in _EFFORT_COLS if c in history_ref.columns]
        effort_hist = quality.reference_frame(history_ref)[effort_cols].fillna(0) \
            if effort_cols else pd.DataFrame()
        effort_daily = effort_hist.sum(axis=1) if not effort_hist.empty else pd.Series(dtype=float)

        # Échelle : le 90e centile des 90 derniers jours mesurés, pas le maximum
        # de tout l'historique. Un maximum est l'otage d'un seul jour — une
        # sortie de deux heures en septembre écraserait toutes les barres de
        # l'année, et la carte deviendrait illisible précisément parce qu'on a
        # fait quelque chose de bien une fois. Le centile suit le train de vie ;
        # les jours hors norme, eux, débordent et se signalent comme tels.
        scale = effort_daily.tail(90)
        effort_scale = float(scale.quantile(0.90)) if len(scale) >= 7 else None

        # Le libellé compte les jours RETENUS, pas les lignes du tableau :
        # « moyenne des 28 derniers jours » sur un historique qui en contient
        # 26 mesurés est un chiffre juste sous une phrase fausse.
        recent = effort_hist.tail(28)
        reference = (
            [(label, float(recent[col].mean())) for label, col in _EFFORT_ZONES
             if col in recent.columns]
            if len(recent) >= 7 else None
        )
        st.markdown(
            charts.effort_bar(
                zone_values, reference, scale_max=effort_scale,
                reference_label=f"moyenne de tes {len(recent)} derniers jours mesurés",
            ),
            unsafe_allow_html=True,
        )

ui.dismissed_summary()

# Profondeur d'historique : une information de fiabilité globale, pas une
# propriété du jour affiché -- elle encombrait la ligne de titre.
#
# Le rendu vit dans `common.page_footer` : cette mention a sa place sur toute
# page qui montre des moyennes, et non sur la seule où elle est née. Le
# raisonnement qui la place en pied (filet, alignement à droite, encre la plus
# effacée) est écrit là-bas.
common.page_footer(full_daily)

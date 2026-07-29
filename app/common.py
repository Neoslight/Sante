"""Sélecteur de période partagé entre toutes les pages (persiste via
st.session_state, donc reste synchronisé quand on navigue entre pages)."""
from __future__ import annotations

import datetime as dt

import pandas as pd
import streamlit as st

import queries
from health import quality

#: Préréglages de fenêtre, en jours (None = tout l'historique). Les libellés
#: sont les CHIFFRES seuls : dans un contrôle segmenté d'une ligne, « 7 derniers
#: jours » écrit quatre fois répète trois mots inutiles et fait déborder la
#: barre latérale.
PRESETS: dict[str, int | None] = {"7": 7, "14": 14, "28": 28, "Tout": None}
DEFAULT_PRESET = "28"


def date_range_picker(title: str = "Période") -> tuple[str, str]:
    """Sélecteur de période, en barre latérale.

    `title` est paramétrable parce que la même longueur de fenêtre ne joue pas
    le même rôle partout : les pages de séries l'utilisent pour choisir CE
    qu'elles affichent, la page du jour seulement pour dire sur combien de
    jours portent ses sparklines et ses variations. Un libellé « Période » y
    laisserait croire que le sélecteur change la journée affichée.

    Contrôle segmenté sur UNE ligne, et non quatre boutons radio empilés : le
    choix est trivial et mutuellement exclusif, il ne mérite pas 120 px de
    hauteur. La période personnalisée, elle, est l'exception — repliée, elle ne
    coûte plus qu'une ligne tant qu'on ne s'en sert pas.
    """
    lo, hi = queries.date_bounds()
    lo, hi = pd.Timestamp(lo).date(), pd.Timestamp(hi).date()

    with st.sidebar:
        st.markdown(f"### {title}")
        choice = st.segmented_control(
            "Préréglage", list(PRESETS.keys()), default=DEFAULT_PRESET,
            label_visibility="collapsed", key="range-preset",
        ) or DEFAULT_PRESET
        days = PRESETS[choice]
        if days is None:
            start, end = lo, hi
        else:
            start = max(lo, hi - dt.timedelta(days=days - 1))
            end = hi
        # Le nombre de jours retenus n'est plus écrit sous le sélecteur : il est
        # désormais lisible sur le segment actif lui-même. Seule la période
        # personnalisée, qui ne correspond à aucun segment, l'affiche encore.
        with st.expander("Période personnalisée"):
            custom = st.checkbox("Utiliser des dates précises", key="range-custom")
            if custom:
                start, end = st.date_input(
                    "Dates", value=(start, end), min_value=lo, max_value=hi,
                )
                n_days = (end - start).days + 1
                plural = "s" if n_days > 1 else ""
                st.caption(f"{n_days} jour{plural} sélectionné{plural}")

    st.session_state["date_range"] = (str(start), str(end))
    return str(start), str(end)


#: Horizons de la page « Progression », en mois (None = tout l'historique).
#: Des MOIS et non des jours : une régression sur quatorze points ne conclut
#: jamais (cf. `stats.trend`, qui exige n >= 10 et p < 0.05), et une page qui
#: pose la question « est-ce que je progresse ? » sur une fenêtre où la réponse
#: est structurellement « on ne peut pas savoir » ne pose pas de question.
HORIZONS: dict[str, int | None] = {"3 mois": 3, "6 mois": 6, "12 mois": 12, "Tout": None}
DEFAULT_HORIZON = "6 mois"


#: Un horizon n'est proposé que si l'historique le remplit AU MOINS à cette
#: fraction. À 0,9, « 3 mois » apparaît vers 81 jours de données : assez pour que
#: la fenêtre soit réellement différente de la précédente, sans exiger le compte
#: rond au jour près.
HORIZON_MIN_FILL = 0.9


def horizon_picker(
    key: str = "horizon", default: str = DEFAULT_HORIZON,
) -> tuple[str, str, int | None]:
    """Sélecteur d'horizon long, rendu EN PAGE et non en barre latérale.

    `date_range_picker` reste le réglage partagé des pages de séries ; celui-ci
    est un paramètre de la question posée par une page précise. Les mélanger
    dans la même barre latérale mettrait deux fenêtres de sens différents sous
    un même mot — le Bilan a déjà dû renommer la sienne « Fenêtre des tuiles »
    pour la même raison.

    Les horizons que l'historique ne remplit pas ne sont PAS proposés. Sur
    39 jours de données, « 3 mois », « 6 mois », « 12 mois » et « Tout »
    renvoyaient tous la même fenêtre : quatre boutons pour un seul résultat.
    Un contrôle mort est pire qu'un contrôle absent — il fait croire au lecteur
    qu'il a déjà tout essayé, et que la page n'a effectivement rien de plus à
    dire. Ils réapparaissent d'eux-mêmes à mesure que l'historique s'allonge.

    Renvoie `(start, end, missing_days)` : les bornes en ISO, et le nombre de
    jours de mesure qui MANQUENT encore avant qu'un réglage d'horizon existe —
    `None` dès qu'un sélecteur a été rendu.

    Ce troisième terme sort d'ici plutôt que d'être écrit en légende sous le
    contrôle absent. Une légende à cet endroit annonçait la profondeur
    d'historique une deuxième fois, à quelques centimètres du badge qui la donne
    déjà — et avec un autre nombre, puisque le badge compte les jours MESURÉS et
    le sélecteur les jours de calendrier. Deux chiffres pour une seule question,
    dont aucun ne disait lequel comptait. L'appelant en fait une clause de son
    badge, ou rien.
    """
    lo, hi = queries.date_bounds()
    lo, hi = pd.Timestamp(lo).date(), pd.Timestamp(hi).date()
    depth_days = (hi - lo).days + 1

    available = {
        label: months for label, months in HORIZONS.items()
        if months is None or depth_days >= months * 30 * HORIZON_MIN_FILL
    }
    if len(available) == 1:
        # « Tout » seul est un contrôle mort lui aussi : rien n'est rendu.
        #
        # Le manque est exprimé en jours RESTANTS, jamais en seuil. « à partir
        # de 81 jours » est une constante interne qui a fui à l'écran : personne
        # ne peut deviner d'où sort 81, ni ce qu'il faut en faire.
        nxt = min(m for m in HORIZONS.values() if m is not None)
        return str(lo), str(hi), max(0, int(nxt * 30 * HORIZON_MIN_FILL) - depth_days)

    choice = st.segmented_control(
        "Horizon", list(available.keys()),
        default=default if default in available else list(available)[0],
        label_visibility="collapsed", key=key,
        help="Les horizons plus longs que l'historique disponible ne sont pas "
             "proposés : ils donneraient tous la même fenêtre.",
    ) or list(available)[0]
    months = available[choice]
    if months is None:
        start = lo
    else:
        # `DateOffset(months=…)` et non `timedelta(days=30 * n)` : « 3 mois »
        # doit tomber sur le même quantième, pas sur 90 jours calendaires.
        start = max(lo, (pd.Timestamp(hi) - pd.DateOffset(months=months)).date())
    return str(start), str(hi), None


#: Fenêtres de la page « Entraînement », en semaines (None = tout l'historique).
#: Des SEMAINES et non des jours : la page est intégralement hebdomadaire
#: (barres empilées, tuiles de semaine), et un préréglage en jours bruts n'a
#: pas de raison de tomber sur un multiple de 7.
WEEK_SPANS: dict[str, int | None] = {"4 sem.": 4, "8 sem.": 8, "12 sem.": 12, "Tout": None}
DEFAULT_WEEKS = "8 sem."


def weeks_picker(key: str = "weeks", default: str = DEFAULT_WEEKS) -> tuple[str, str, int | None]:
    """Sélecteur de fenêtre en semaines, rendu EN PAGE — même contrat que `horizon_picker`.

    Bornes alignées sur le LUNDI de la semaine de `hi`, pas sur un compte de
    jours bruts : une fenêtre de 28 jours calendaires tombe presque toujours
    au milieu d'une semaine, et coupe donc en deux la première ou la dernière
    des barres empilées qu'elle alimente — une semaine tronquée à côté de
    semaines pleines fausserait la comparaison plus qu'elle ne la permettrait.

    « 4 sem. » compte quatre semaines CLOSES, et la fenêtre en couvre donc
    cinq : celle de `hi` est en cours, et la page qui appelle ce sélecteur
    l'écarte de ses agrégats hebdomadaires — une semaine arrêtée un mardi
    n'est pas comparable à ses voisines. Reculer de `n - 1` semaines rendrait
    l'étiquette fausse : le lecteur choisirait quatre semaines et en verrait
    trois dessinées.

    Mêmes règles que `horizon_picker`, pour les mêmes raisons — un span que
    l'historique ne remplit pas n'est pas proposé, et s'il n'en reste qu'un
    seul, aucun contrôle n'est rendu (cf. la docstring de `horizon_picker`
    ci-dessus, non recopiée ici).

    Renvoie `(start, end, missing_days)` avec exactement la même sémantique
    que `horizon_picker` : bornes en ISO, `missing_days` = jours de mesure
    manquants avant qu'un deuxième span existe, `None` dès qu'un sélecteur a
    été rendu.
    """
    lo, hi = queries.date_bounds()
    lo, hi = pd.Timestamp(lo).date(), pd.Timestamp(hi).date()
    depth_days = (hi - lo).days + 1

    # `n + 1` semaines de profondeur exigées pour n semaines closes : la
    # semaine de `hi` est en cours et ne compte pas.
    def _needed(n: int) -> int:
        return int((n + 1) * 7 * HORIZON_MIN_FILL)

    available = {
        label: n for label, n in WEEK_SPANS.items()
        if n is None or depth_days >= _needed(n)
    }
    if len(available) == 1:
        nxt = min(n for n in WEEK_SPANS.values() if n is not None)
        return str(lo), str(hi), max(0, _needed(nxt) - depth_days)

    choice = st.segmented_control(
        "Semaines", list(available.keys()),
        default=default if default in available else list(available)[0],
        label_visibility="collapsed", key=key,
        help="Les fenêtres plus longues que l'historique disponible ne sont "
             "pas proposées : elles donneraient toutes la même période.",
    ) or list(available)[0]
    n = available[choice]
    if n is None:
        start = lo
    else:
        # Lundi de la semaine de `hi`, reculé de n semaines : la fenêtre couvre
        # les n dernières semaines CLOSES, plus celle en cours.
        monday_hi = hi - dt.timedelta(days=hi.weekday())
        start = max(lo, monday_hi - dt.timedelta(weeks=n))
    return str(start), str(hi), None


#: Noms de jours et de mois écrits à la main : le serveur qui fait tourner
#: Streamlit n'a pas forcément la locale `fr_FR` installée, et
#: `locale.setlocale` échouerait silencieusement en prod.
WEEKDAYS_FR = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MONTHS_FR = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]


def format_fr_date(d: dt.date, weekday: bool = True, year: bool = True) -> str:
    """Date en français longue ("samedi 25 juillet 2026") ou courte ("25 juillet").

    Ici et non dans une page : deux pages en ont besoin, et la seconde à en
    avoir eu besoin allait recopier le tableau des mois.
    """
    out = f"{d.day} {MONTHS_FR[d.month - 1]}"
    if weekday:
        out = f"{WEEKDAYS_FR[d.weekday()]} {out}"
    return f"{out} {d.year}" if year else out


#: Gabarit des titres d'onglet. Le Bilan annonçait « Santé — Aujourd'hui » et
#: les six autres pages leur seul nom : dans une barre d'onglets de navigateur,
#: rien ne rattachait « Progression » à la même application que « Santé ».
PAGE_TITLE = "Santé — {}"


def head_title_html(text: str, page_title: bool = False) -> str:
    """La ligne de titre d'une page, en HTML.

    UNE seule définition pour les deux gabarits d'en-tête : la date longue du
    Bilan, prise entre ses chevrons de navigation, et la question qui tient
    l'en-tête des pages de série. Ce sont deux mises en page différentes mais
    la même famille typographique — dupliquée, elle divergeait au premier
    réglage.

    `page_title` monte au cran supérieur (22 px). Les deux en-têtes étaient au
    MÊME corps, 15 px, et c'est justement le problème : sur le Bilan, la date
    tient le centre d'une barre de commandes compacte et l'entourage lui donne
    son poids ; seule en haut à gauche d'une page de série, la même taille
    retombe au rang d'intitulé de section. Or c'est le titre de la page et sa
    question directrice.

    La date du Bilan, elle, reste à 15 px : elle vit dans une barre dont les
    boutons font 32 px de haut, et la grossir déséquilibrerait la barre entière
    pour un gain nul — l'entourage fait déjà le travail.
    """
    cls = "bevel-daydate bevel-pagetitle" if page_title else "bevel-daydate"
    return f'<div class="bevel-dayhead"><span class="{cls}">{text}</span></div>'


def page_head(title: str, right: bool = True):
    """En-tête de page : le titre à gauche, un contrôle à droite.

    Renvoie la colonne de droite (ou `None` si `right=False`), à remplir par
    l'appelant avec son propre contrôle — un sélecteur d'horizon, une période.

    Le conteneur porte la clé `pagehead`, qui déclenche le rythme vertical et la
    correction de boîte de `theme.css()`. Sans lui, un `st.columns` nu se colle
    au bord supérieur et le titre retombe de 6,5 px sous le contrôle voisin :
    Streamlit pose `margin-bottom: -13px` sur ses conteneurs de markdown, si
    bien que `vertical_alignment="center"` centre une boîte plus courte que le
    texte qu'elle contient. C'est le réglage qu'on a mesuré une fois pour le
    Bilan — le partager évite de le remesurer par page.
    """
    with st.container(key="pagehead"):
        if not right:
            st.markdown(head_title_html(title, page_title=True), unsafe_allow_html=True)
            return None
        left_col, right_col = st.columns([3, 2], vertical_alignment="center")
        with left_col:
            st.markdown(head_title_html(title, page_title=True), unsafe_allow_html=True)
        return right_col


def page_footer(df: pd.DataFrame) -> None:
    """Pied de page : profondeur d'historique et dernier jour connu.

    Une mention de fiabilité, pas une donnée du jour — d'où le filet, l'encre la
    plus effacée et l'alignement à droite, hors du chemin de lecture. Elle a sa
    place sur TOUTE page qui montre des moyennes, et pas seulement sur le Bilan
    où elle est née : c'est même sur « Progression » qu'elle compte le plus,
    puisque tout y est régression et que la profondeur décide de ce qui est
    concluant.

    Le compte passe par `quality.count_measured` : `len(df)` compterait les
    lignes du calendrier, jours sans montre compris — la profondeur du
    calendrier, pas celle des données.
    """
    if df is None or df.empty or "local_date" not in df.columns:
        return
    last = pd.to_datetime(df["local_date"]).max().date()
    st.markdown(
        f'<div class="bevel-footer">{quality.count_measured(df)} jours mesurés · '
        f"dernier jour connu : {format_fr_date(last)}</div>",
        unsafe_allow_html=True,
    )


def previous_period(start: str, end: str) -> tuple[str, str]:
    """Période de même longueur précédant immédiatement [start, end], pour les deltas."""
    s = pd.Timestamp(start)
    e = pd.Timestamp(end)
    n_days = (e - s).days + 1
    prev_end = s - dt.timedelta(days=1)
    prev_start = prev_end - dt.timedelta(days=n_days - 1)
    return str(prev_start.date()), str(prev_end.date())


def kpi_delta_str(value: float | None, prev: float | None, unit: str = "", fmt: str = "{:+.0f}") -> str | None:
    d = queries.delta(value, prev)
    if d is None:
        return None
    return f"{fmt.format(d)}{unit}"

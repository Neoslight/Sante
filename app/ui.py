"""Primitives de mise en page Bevel : carte et grille de KPI.

Module volontairement isolé du reste du repo (aucun import de `charts` ou
`theme`) pour rester trivialement importable. Le fond, le radius et le
padding des cartes viennent du CSS injecté par `theme.inject_css()` ; ce
module ne pose aucune couleur ni dimension en dur, il se contente
d'assembler les conteneurs Streamlit et les classes CSS attendues.
"""
from __future__ import annotations

import datetime as _dt
import hashlib as _hashlib
import html as _html
from contextlib import contextmanager
from typing import Callable

import streamlit as st

# Balise invisible posée en tête de chaque carte. Streamlit n'expose AUCUN
# `data-testid` propre aux conteneurs bordés depuis la 1.60 (le proto est passé
# à `flex_container.border`, rendu par une classe emotion générée) : styler
# `[data-testid="stVerticalBlock"]` toucherait en revanche TOUS les blocs de
# layout, y compris le corps de page et les colonnes. Ce marqueur donne au CSS
# de `theme.inject_css()` un point d'ancrage stable, ciblé via `:has()` sur le
# bloc parent immédiat — Streamlit utilise lui-même `:has()` dans son bundle,
# donc c'est dans sa baseline navigateur.
_CARD_MARKER = '<span class="bevel-card-marker"></span>'


@contextmanager
def card(title: str | None = None, caption: str | None = None,
         info: str | dict[str, str] | None = None):
    """Carte Bevel : `st.container(border=True)` + en-tête optionnel.

    Si `title` est fourni, un unique `st.markdown` rend titre (et légende, si
    fournie) avec les classes `.bevel-card-title` / `.bevel-card-caption`
    avant de céder le contrôle à l'appelant pour le contenu de la carte.

    `info` rend un bouton « ? » à droite du titre, qui ouvre TOUTES les
    explications de la carte d'un coup (`dict` : libellé -> explication ; une
    chaîne simple reste acceptée pour les cartes à explication unique).

    Un `st.popover` et non un attribut `title=` HTML : l'infobulle native ne
    s'ouvre pas au tactile, et une pastille « i » par métrique — il y en avait
    neuf sur la page du jour — sature l'écran pour un contenu qu'on consulte
    une fois par mois. Un bouton par carte, et le texte long garde sa place en
    clair dans le Glossaire.

    `title`, `caption` et `info` sont échappés : les appelants y passent des
    textes du registre de métriques (`metric.how_read`, etc.), et
    `charts.kpi_card` échappe déjà les siens — les deux blocs HTML du
    dashboard suivent la même règle.
    """
    with st.container(border=True):
        header = _CARD_MARKER
        if title:
            header += f'<div class="bevel-card-title">{_html.escape(title)}</div>'
            if caption:
                header += f'<div class="bevel-card-caption">{_html.escape(caption)}</div>'
        st.markdown(header, unsafe_allow_html=True)
        if info:
            # Le bouton d'aide sort du FLUX (positionné en absolu par le CSS,
            # coin haut-droit de la carte) au lieu d'occuper une colonne.
            #
            # Une `st.columns` mettait le marqueur de carte à l'intérieur de la
            # colonne de titre : ce bloc-là matchait alors le sélecteur de carte
            # et se peignait en carte, d'où une boîte de 90 px dans la boîte,
            # avec son propre fond, pour porter un titre de 15 px. Le contenant
            # pesait dix fois le contenu.
            _help_popover(info, title or "")
        yield


def _help_popover(info: str | dict[str, str], title: str) -> None:
    """Bouton « ? » d'une carte, et son contenu déplié.

    Enveloppé dans un conteneur à clé : `st.popover` n'accepte pas de `key`, et
    sans point d'ancrage propre, le CSS qui rend CE bouton discret s'appliquait
    aussi au sélecteur de date de l'en-tête, qui perdait alors 10 px de hauteur
    et ne s'alignait plus avec les boutons voisins. Cette clé sert aussi au
    positionnement absolu du bouton sur la ligne du titre.

    La clé dérive du titre : deux cartes de même titre sur une même page
    partageraient leur conteneur, ce qui lèverait côté Streamlit. Aucun cas
    aujourd'hui — un titre de carte dupliqué serait de toute façon un défaut de
    rédaction.
    """
    with st.container(key=f"cardhelp-{_hashlib.sha1(title.encode()).hexdigest()[:8]}"):
        with st.popover("?", help=f"Comment lire « {title} »" if title else "Aide"):
            if isinstance(info, str):
                st.write(info)
                return
            for label, text in info.items():
                st.markdown(f"**{label}** — {text}")


def _one_line(text: str) -> str:
    """Texte prêt à poser dans un attribut HTML : échappé ET aplati.

    Une ligne vide au milieu d'un attribut clôt le bloc HTML côté markdown
    Streamlit — la fin de l'attribut, `">` compris, se retrouve alors rendue
    en texte au-dessus du composant (bug déjà corrigé dans `charts.kpi_card`).
    """
    return _html.escape(" ".join(text.split()))


def kpi_row(items: list, render: Callable, per_row: int = 4) -> None:
    """Découpe `items` en rangées de `per_row` colonnes et appelle
    `render(item)` dans chaque colonne.

    Quand la dernière rangée est incomplète, elle garde tout de même
    `per_row` colonnes (les colonnes surnuméraires restent simplement
    vides) : les tuiles conservent ainsi la même largeur d'une rangée à
    l'autre, plutôt que d'étirer les tuiles restantes sur toute la largeur.
    """
    items = list(items)
    for i in range(0, len(items), per_row):
        row = items[i:i + per_row]
        cols = st.columns(per_row)
        for col, item in zip(cols, row):
            with col:
                render(item)


def _to_date(value) -> _dt.date:
    """Normalise une date ISO (str) ou un `date`/`Timestamp` en `date` nu.

    Les appelants passent parfois des `local_date` remontés de DuckDB (déjà
    des `date`), parfois des chaînes ISO construites à la main (clés de
    session, bornes de sélecteur) : ce module ne doit pas dupliquer cette
    logique de conversion à chaque site d'appel.
    """
    if isinstance(value, str):
        return _dt.date.fromisoformat(value)
    if hasattr(value, "date") and not isinstance(value, _dt.date):
        return value.date()
    return value


def day_strip(
    days: list, labels: list[str], colors: list[str | None], selected,
    key_prefix: str = "daystrip", weekday_labels: list[str] | None = None,
    today=None,
) -> object | None:
    """Bande de jours cliquables — le sélecteur de date principal.

    `weekday_labels` (initiales L M M J V S D) place le repère hebdomadaire à
    côté de la pastille : sans lui, une bande de quatorze numéros ne dit pas
    où tombent les week-ends, alors que c'est la structure même d'une semaine
    d'entraînement.

    Trois états, trois traitements — c'est le point qui manquait le plus :
    SÉLECTIONNÉ (fond d'accent plein), AUJOURD'HUI (contour d'accent), NORMAL
    (fond discret). Confondre les deux premiers rend la bande inutilisable dès
    qu'on navigue dans le passé : plus rien ne dit d'où l'on vient.

    `colors` : couleur de la pastille sous chaque jour, `None` pour une
    pastille creuse (jour sans mesure) -- ne jamais colorer un jour sans
    donnée laisserait croire qu'il a un état. La clé de chaque bouton est
    l'ISO du jour (pas son index dans la liste) : elle reste stable si la
    fenêtre de jours affichée glisse d'un jour à l'autre entre deux reruns.

    Retourne le jour cliqué ce rerun (objet d'origine, pas converti), sinon
    `None` -- toutes les colonnes sont rendues avant de statuer, un seul bouton
    peut être vrai par rerun mais il faut quand même dessiner les autres.
    """
    clicked = None
    cols = st.columns(len(days))
    wd_labels = weekday_labels or [""] * len(days)
    today_date = _to_date(today) if today is not None else None
    if today_date is not None:
        # Contour d'aujourd'hui. Streamlit ne permet pas de poser une classe
        # sur un bouton : la seule prise stable est la classe `st-key-<key>`
        # qu'il dérive de la clé du widget, d'où cette règle ciblée émise ici
        # plutôt que dans `theme.inject_css()`, qui ne connaît pas la date du
        # jour. La couleur, elle, vient bien du CSS global : ce module ne pose
        # aucune valeur de thème, il ne fait que désigner la cible.
        st.markdown(
            f"<style>[class*='st-key-{key_prefix}-{today_date.isoformat()}'] button"
            "{box-shadow:inset 0 0 0 1px var(--bevel-accent)}</style>",
            unsafe_allow_html=True,
        )
    previous_month = None
    for col, day, label, color, wd in zip(cols, days, labels, colors, wd_labels):
        d = _to_date(day)
        iso = d.isoformat()
        is_selected = d == _to_date(selected)
        # Filet vertical au changement de mois. La date en toutes lettres
        # au-dessus de la bande ne suffit que tant que la bande ne franchit pas
        # de mois : le 3 août, elle affiche « 21 22 … 31 01 02 03 » sous un
        # titre qui ne dit qu'« août », et rien ne signale que la moitié gauche
        # est de juillet. Le repère n'apparaît QUE là où il y a une frontière —
        # une bande à l'intérieur d'un même mois n'en porte aucun.
        starts_month = previous_month is not None and d.month != previous_month
        previous_month = d.month
        if starts_month:
            # Le filet est posé sur la COLONNE entière (via `:has()`) et non sur
            # le conteneur du bouton : la clé `st-key-` que Streamlit dérive du
            # widget n'existe que sur ce dernier, où le filet ne couvrirait que
            # les 32 px du bouton et laisserait l'initiale du jour et sa
            # pastille du mauvais côté de la frontière.
            st.markdown(
                f"<style>[data-testid='stColumn']:has([class*='st-key-{key_prefix}-{iso}'])"
                "{border-left:1px solid var(--bevel-border)}</style>",
                unsafe_allow_html=True,
            )
        with col:
            if color is None:
                dot_style = "background:transparent;border:1px solid currentColor"
            else:
                dot_style = f"background:{color}"
            # Conteneur flex explicite : un `margin: 0 auto` sur la pastille
            # dépend de la largeur que Streamlit donne au bloc markdown, qui
            # n'est pas garantie égale à celle du bouton — la pastille se
            # décalait alors à gauche du numéro qu'elle qualifie.
            wd_html = (
                f'<span class="bevel-daystrip-weekday">{_html.escape(wd)}</span>' if wd else ""
            )
            st.markdown(
                f'<div class="bevel-daystrip-dotwrap">{wd_html}'
                f'<span class="bevel-daystrip-dot" style="{dot_style}"></span></div>',
                unsafe_allow_html=True,
            )
            if st.button(
                label, key=f"{key_prefix}-{iso}",
                type="primary" if is_selected else "secondary", width="stretch",
            ):
                clicked = day
    return clicked


def notice(text: str, kind: str = "info", msg_id: str | None = None, icon: str | None = None) -> None:
    """Bandeau fermable (`.bevel-notice`), portée session.

    `msg_id` par défaut dérive du COUPLE (kind, text) plutôt que du seul
    texte : une alerte ACWR redevenue pertinente après avoir changé de valeur
    change de `msg_id` (l'appelant passe alors la valeur chiffrée dans le
    texte ou le `msg_id`) et réapparaît, alors qu'un message identique reste
    masqué -- sans le `kind` dans le hash, un même libellé utilisé une fois en
    "info" et une fois en "warning" partagerait à tort son état masqué.

    Fermer une notice modifie `st.session_state` en dehors du cycle normal
    d'un widget Streamlit (le bouton "✕" n'a pas de valeur affichée à faire
    persister) : sans `st.rerun()` explicite après l'ajout au set, le
    bandeau resterait visible jusqu'au prochain événement utilisateur
    ailleurs sur la page.
    """
    msg_id = msg_id or _notice_id(text, kind)
    dismissed: set = st.session_state.setdefault("dismissed_notices", set())
    if msg_id in dismissed:
        return

    left, right = st.columns([40, 1])
    with left:
        icon_html = f'<span class="bevel-notice-icon">{_html.escape(icon)}</span> ' if icon else ""
        st.markdown(
            f'<div class="bevel-notice bevel-notice-{kind}">{icon_html}'
            f'<span class="bevel-notice-text">{_html.escape(text)}</span></div>',
            unsafe_allow_html=True,
        )
    with right:
        if st.button("✕", key=f"notice-x-{msg_id}", help="Masquer ce message"):
            dismissed.add(msg_id)
            st.rerun()


def _notice_id(text: str, kind: str) -> str:
    """Extrait pour être testable sans session Streamlit (cf. tests/test_ui.py)."""
    return _hashlib.sha1((kind + text).encode()).hexdigest()[:12]


def dismissed_summary() -> None:
    """Ligne discrète « n message(s) masqué(s) — Réafficher » en bas de page.

    Sans ce rappel, un message fermé par erreur (ou une alerte qu'on veut
    revoir plus tard) disparaîtrait sans recours jusqu'au prochain
    changement de contenu -- la portée session de `notice()` n'a de sens que
    si elle reste réversible dans la même session.
    """
    dismissed: set = st.session_state.get("dismissed_notices", set())
    if not dismissed:
        return
    left, right = st.columns([5, 1])
    with left:
        st.caption(f"{len(dismissed)} message(s) masqué(s)")
    with right:
        if st.button("Réafficher", key="notice-restore"):
            dismissed.clear()
            st.rerun()


def empty_state(text: str, hint: str | None = None) -> None:
    """Bloc muet centré (`.bevel-empty`) à afficher DANS une carte à la place
    d'un graphe vide -- un graphe Plotly vide (axes, grille, légende) prétend
    à tort qu'il y a quelque chose à lire ; ce bloc dit explicitement qu'il
    n'y a rien, et pourquoi (`hint`) si l'appelant peut le préciser.
    """
    hint_html = f'<div class="bevel-empty-hint">{_html.escape(hint)}</div>' if hint else ""
    st.markdown(
        f'<div class="bevel-empty"><div>{_html.escape(text)}</div>{hint_html}</div>',
        unsafe_allow_html=True,
    )

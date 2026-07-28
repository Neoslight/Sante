"""Thème visuel du dashboard : jetons clair/sombre + CSS de mise en page.

Pourquoi ce module existe : Streamlit choisit son thème (réglage utilisateur ou
thème de l'OS), mais Plotly l'ignore complètement — un graphe construit avec
`SURFACE = "#fcfcfb"` codé en dur reste un rectangle clair sur un fond sombre
dès que l'utilisateur passe en thème sombre. `active_tokens()` est LA fonction
que `charts.py` appelle pour obtenir le bon jeu de couleurs ; tout le reste
(palette catégorielle, statut, texte) en découle et ne doit plus jamais être
écrit en dur ailleurs.

**Règle typographique des séparateurs**, valable pour tout texte du dashboard —
trois signes utilisés au hasard pour trois fonctions différentes rendent une
ligne méta illisible avant même d'en avoir lu les mots :

    « : »  libellé -> valeur           « Fond : 28,2 »
    « · »  éléments de même nature     « 66 % FC · 39 j »
    « — »  verdict -> nuance           « Frais — récupération en retrait »

**Sémantique des couleurs**, close elle aussi :

    famille ROUGE   signal physiologique — `serious` (notable) puis `critical`
    AMBRE           la donnée est incomplète ou non fiable, jamais le corps
    VERT            l'accent : rien à signaler, et le jour choisi dans la bande
    BLEU / ORANGE   `chart_pair`, réservé à la seule courbe fond/fatigue
    ENCRE           tout le reste, c'est-à-dire l'essentiel de l'écran

Budget : au plus DEUX éléments colorés visibles à la fois. Sur la page du jour,
ce sont l'anneau du verdict et sa nuance dominante — rien d'autre. Les tuiles,
la barre de zones et les paliers de la jauge sont en encre ; la bande de jours
n'utilise l'accent que pour dire où l'on est.

Une seule chose se pose HORS budget : le badge ambre de journée incomplète. Il
ne désigne pas un élément de la page, il qualifie tout ce qu'elle affiche —
sans lui, un verdict calculé sur 26 % de couverture se lirait comme un verdict
ordinaire. Il n'apparaît que lorsqu'il y a un défaut : une pastille verte
« journée complète » serait, elle, une alerte pour dire qu'il n'y a pas
d'alerte.

Les deux jeux de tokens sont le miroir Python de `.streamlit/config.toml`
(section [theme]) — TOML ne peut pas importer du Python, donc toute
modification d'un côté doit être répercutée manuellement de l'autre. Le
défaut de l'application est désormais le thème sombre "Bevel" : fond
quasi-noir, cartes surélevées à grand radius, palette désaturée.
"""
from __future__ import annotations

from pathlib import Path

import streamlit as st

# --- Jetons sombres (défaut) --------------------------------------------
#
# Les encres sont des GRIS NEUTRES et non des gris bleutés : ce sont les
# opacités du système (.92 / .60 / .38 de blanc) aplaties sur la surface d'une
# carte. Aplaties, et pas laissées en `rgba()`, parce que `charts._with_opacity`
# et `theme._rgba` parsent des hex — un jeton semi-transparent y lèverait, et
# Plotly ne compose pas non plus l'alpha de la même façon selon la trace.
DARK: dict = {
    "mode": "dark",
    "page": "#0A0A0B",
    "surface": "#101012",
    "surface_raised": "#17171A",
    "border": "rgba(255,255,255,0.06)",
    "grid": "#1B1B1F",
    "baseline": "#26262B",
    "ink_primary": "#ECECEC",    # blanc .92
    "ink_secondary": "#9F9FA0",  # blanc .60
    "ink_muted": "#6B6B6C",      # blanc .38
    "success_text": "#3FBF95",
    # L'accent UNIQUE de l'application : la couleur de la Forme quand tout va
    # bien. Elle ne sert qu'à deux choses — désigner le jour choisi dans la
    # bande, et colorer l'anneau du verdict via le statut. Tout le reste est
    # en encre.
    "accent": "#3FBF95",
    # Duo RÉSERVÉ à la courbe fond/fatigue : deux séries sur un même axe sont
    # le seul endroit du dashboard où deux teintes doivent coexister. Ailleurs,
    # la couleur est un signal de statut, jamais une identité de série.
    "chart_pair": ["#5B9CF6", "#F08A4B"],
    # Ordre catégoriel fixe (jamais recyclé) — cf. references/palette.md du skill
    # dataviz. N'a plus cours sur la page du jour ; sert aux pages de détail où
    # plusieurs séries partagent un axe (groupes musculaires, sous-scores).
    "categorical": [
        "#5B9CF6", "#F08A4B", "#3FBF95", "#E0B341",
        "#D97BA8", "#7B9E5C", "#9B8CF0", "#EB6E6E",
    ],
    # Palette d'IDENTITÉ des séries, distincte de `categorical` parce que
    # celle-ci empiétait sur le budget de statut : son slot 2 valait EXACTEMENT
    # `status.good` et son slot 7 `status.critical` (en clair). La VO2max était
    # donc tracée en vert-« bon » et la fréquence de repos en rouge-« alerte » :
    # une courbe rouge qui monte crie l'alarme sur une métrique qui n'a aucun
    # seuil, et la règle « survole une tuile pour retrouver sa teinte ailleurs »
    # n'a de sens que si la teinte est une identité et non un jugement.
    #
    # Quatre slots réassignés — les quatre qui touchaient au vert, à l'ambre ou
    # au rouge. Les quatre autres sont inchangés : ils ne portent aucun jugement.
    #
    # Le slot 7 a été réassigné DEUX fois. Sa première correction, une ardoise
    # (#8AA0B8), échappait bien au budget de statut mais tombait dans l'autre
    # piège : à 0,24 de saturation, elle appartenait de fait à la famille des
    # encres — celle de la grille, des axes et du pointillé de normale. Le graphe
    # de FC de repos paraissait désactivé à côté de ses voisins, parce que sa
    # teinte disait « chrome » et non « donnée ». D'où le plancher de saturation
    # vérifié par les tests du système visuel.
    #
    # Ocre, et non une quatrième teinte froide : les métriques de la page
    # « Progression » occupaient 188 à 249 degrés, soit une seule famille de
    # bleus dont l'œil ne tire aucune segmentation. Le créneau chaud est étroit —
    # l'ambre (#E0B341) appartient au budget de fiabilité et les rouges au
    # statut — d'où un ocre franchement moins lumineux que l'ambre et bien moins
    # saturé que l'orange du slot 1.
    "series": [
        "#5B9CF6",  # bleu
        "#F08A4B",  # orange
        "#46C2D6",  # cyan          (ex-vert, = status.good)
        "#C9A46B",  # sable         (ex-ambre, = status.warning)
        "#D97BA8",  # rose
        "#3E8E9E",  # bleu profond  (ex-olive, famille du vert)
        "#9B8CF0",  # violet
        "#C4885F",  # ocre          (ex-rouge, puis ex-ardoise — cf. ci-dessous)
    ],
    # Grille horizontale : une encre à faible opacité, et non une couleur pleine.
    # `grid` (#1B1B1F) sur une carte à #101012 était invisible — les graphes
    # n'avaient de fait aucune graduation, et aucune valeur intermédiaire ne
    # pouvait s'y lire.
    # 4,5 % et non 6 % : à deux graduations, chaque ligne pèse plus lourd, et la
    # grille traverse la bande de zone normale (elle-même à 10 %). Deux trames
    # d'opacité voisines qui se croisent se lisent comme un moiré, pas comme deux
    # niveaux de lecture.
    "grid_line": "rgba(255,255,255,0.045)",
    # Rampe séquentielle bleue : en sombre, "proche de zéro" doit se fondre
    # vers la surface SOMBRE, donc du plus foncé vers le plus clair.
    "sequential": ["#0E2440", "#16406F", "#1F5A9E", "#2E77CB", "#5B9CF6", "#8FBEF9", "#C6DDFC"],
    "diverging_low": "#E5615F",   # pôle négatif (rouge)
    "diverging_high": "#5B9CF6",  # pôle positif (bleu)
    "diverging_mid": "#2A2F33",
    "status": {"good": "#3FBF95", "warning": "#E0B341", "serious": "#E9928C", "critical": "#E5615F"},
}

# --- Jetons clairs --------------------------------------------------------
LIGHT: dict = {
    "mode": "light",
    "page": "#F5F5F5",
    "surface": "#FFFFFF",
    "surface_raised": "#F0F0F0",
    "border": "rgba(0,0,0,0.08)",
    "grid": "#E8E8E8",
    "baseline": "#CFCFCF",
    # Mêmes opacités que le sombre, en noir sur blanc : .92 / .60 / .38.
    "ink_primary": "#141414",
    "ink_secondary": "#666666",
    "ink_muted": "#9E9E9E",
    "success_text": "#0F7A57",
    "accent": "#0F9A72",
    "chart_pair": ["#2A6FD6", "#D9662C"],
    "categorical": [
        "#2A6FD6", "#D9662C", "#0F9A72", "#B8860B",
        "#C25587", "#5E7D42", "#6B5BD0", "#CE4B4B",
    ],
    # Mêmes réassignations que le sombre, en versions assez foncées pour tenir
    # sur blanc (cf. le commentaire de `series` côté sombre).
    "series": [
        "#2A6FD6",  # bleu
        "#D9662C",  # orange
        "#1C89A6",  # cyan
        "#9A7B3A",  # sable
        "#C25587",  # rose
        "#2E6C7A",  # bleu profond
        "#6B5BD0",  # violet
        "#9A5F35",  # ocre
    ],
    "grid_line": "rgba(0,0,0,0.045)",
    # Même rampe que le sombre, mais l'ancre s'inverse (cf. skill dataviz,
    # "flips anchor in dark") : en clair, "proche de zéro" doit se fondre vers
    # la surface claire, donc du plus clair vers le plus foncé.
    "sequential": ["#C6DDFC", "#8FBEF9", "#5B9CF6", "#2E77CB", "#1F5A9E", "#16406F", "#0E2440"],
    "diverging_low": "#CE4B4B",
    "diverging_high": "#2A6FD6",
    "diverging_mid": "#EDEDE9",
    "status": {"good": "#0F9A72", "warning": "#B8860B", "serious": "#D07770", "critical": "#CE4B4B"},
}

# Invariant non négociable (tests/test_charts.py:73) : la rampe séquentielle
# du clair est l'exact inverse de celle du sombre. Assertion au niveau module
# pour documenter la contrainte et empêcher une régression silencieuse si
# l'une des deux listes est modifiée sans l'autre.
assert LIGHT["sequential"] == list(reversed(DARK["sequential"])), (
    "LIGHT['sequential'] doit être l'exact reversed() de DARK['sequential']"
)


def _detect_mode() -> str:
    """Détecte le thème actif de la session Streamlit courante.

    `theme.base` de `.streamlit/config.toml` d'ABORD, `st.context.theme.type`
    seulement en repli.

    Cet ordre est l'inverse de l'intuition, et il vient d'une mesure : avec un
    navigateur dont la préférence système est CLAIRE, `st.context.theme.type`
    renvoie "light" alors que Streamlit applique bel et bien le thème sombre
    épinglé par la config. Le module servait donc des jetons clairs sous une
    interface sombre — cartes blanches sur fond noir. La config est la décision
    de l'application ; le contexte ne fait que rapporter une préférence du
    navigateur, qui n'a pas cours ici tant que `base` est épinglé.

    Hors contexte de script (tests, script de fumée), les deux renvoient None
    sans lever : on retombe alors sur "dark", le défaut de la config.
    """
    try:
        base = st.get_option("theme.base")
        if base in ("light", "dark"):
            return base
    except Exception:
        pass
    try:
        theme_type = st.context.theme.type
        if theme_type in ("light", "dark"):
            return theme_type
    except Exception:
        pass
    return "dark"


def active_tokens() -> dict:
    """Le jeu de tokens (clair ou sombre) à utiliser pour CE rerun Streamlit."""
    return DARK if _detect_mode() == "dark" else LIGHT


def _rgba(hex_color: str, alpha: float) -> str:
    """Hex -> rgba(), pour les fonds tintés des notices.

    Même logique que `charts._with_opacity`, dupliquée ici plutôt
    qu'importée : `theme.py` est la fondation dont dépend `charts.py`
    (jamais l'inverse), donc un import de `charts` depuis ce module créerait
    une dépendance circulaire.
    """
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def inject_css() -> None:
    """Injecte le CSS de mise en page global du dashboard.

    Ne stylise plus `stMetric` (les tuiles KPI passent par un bloc HTML dédié
    dans `charts.kpi_card`) : ce module pose désormais la charte visuelle
    partagée (cartes, typographie, dataframes) ainsi qu'un jeu de classes
    utilitaires qui forment l'INTERFACE PUBLIQUE consommée par `app/ui.py` et
    les pages pour construire leurs propres blocs HTML :

        .bevel-kpi                la tuile KPI (conteneur)
        .bevel-kpi-top            ligne libellé + pastille
        .bevel-kpi-label          libellé de la métrique
        .bevel-kpi-value          valeur principale (chiffres tabulaires)
        .bevel-kpi-delta          ligne variation + libellé de statut
        .bevel-kpi-delta-value    la variation chiffrée seule (couleur inline)
        .bevel-kpi-status-label   le libellé de statut seul (couleur inline)
        .bevel-kpi-spark          la sparkline SVG inline
        .bevel-kpi-scale          bornes min/max de la fenêtre, sous la sparkline
        .bevel-chart-head         en-tête de graphe (conteneur des trois lignes)
        .bevel-chart-title        titre du graphe, quand la carte ne le nomme pas
        .bevel-chart-note         pente et réserve de fiabilité
        .bevel-group-note         légende du pointillé, au bout de l'intitulé
        .bevel-spark-line         la courbe (teinte pilotée par --bevel-spark)
        .bevel-spark-fill         l'aire sous la courbe
        .bevel-spark-dot          le point du jour, au bout de la courbe
        .bevel-group              intitulé de groupe de tuiles
        .bevel-group-gap          le même, précédé d'un groupe
        .bevel-effort             bloc « temps par intensité » (conteneur)
        .bevel-effort-bar         la barre empilée du jour
        .bevel-effort-seg         un segment d'intensité
        .bevel-effort-over        chevron de dépassement d'échelle
        .bevel-effort-ghost       la barre de référence sur 28 jours
        .bevel-effort-ref         sa légende
        .bevel-effort-legend      la légende des intensités, sous la barre
        .bevel-effort-key         une entrée de cette légende
        .bevel-dot                pastille de statut (good/warning/serious/critical)
        .bevel-card-title         titre de carte
        .bevel-card-caption       sous-titre / légende de carte
        .bevel-kpi-pill           pastille de variation vs baseline
        .bevel-verdict            verdict unique du jour (conteneur)
        .bevel-verdict-headline   la phrase d'état, seule affirmation de la page
        .bevel-verdict-score      le score, à la taille de la phrase
        .bevel-verdict-hint       conduite à tenir, sous le verdict
        .bevel-verdict-aside      constat de niveau non testé, sous les nuances
        .bevel-nuance             ligne de nuance sous le verdict
        .bevel-rail               réglette de position sur l'échelle de forme
        .bevel-rail-track         piste de la réglette (zones colorées)
        .bevel-rail-cursor        position du jour
        .bevel-rail-zones         boîte des paliers (arrondi + rognage)
        .bevel-rail-zone          un palier
        .bevel-rail-ghost         position d'il y a 7 jours
        .bevel-rail-ghost-label   son nom, en clair
        .bevel-rail-notes         rangée qui porte ce nom
        .bevel-rail-labels        noms des zones, sous la piste
        .bevel-daystrip-dotwrap   centrage de la pastille sur son bouton
        .bevel-dayhead            en-tête du jour sélectionné (conteneur)
        .bevel-daydate            date longue en français, en-tête du jour
        .bevel-pagetitle          le même, au cran de titre de page (22 px)
        .bevel-daymeta            ligne méta sous la date (historique, etc.)
        .bevel-badge              badge qualité de données (conteneur)
        .bevel-badge-dot          pastille du badge qualité de données
        .bevel-daystrip-dot       pastille de statut au-dessus de chaque bouton
                                  de la bande de 14 jours
        .bevel-daystrip-label     libellé optionnel sous la bande de jours
        .bevel-notice             bandeau de message fermable (conteneur)
        .bevel-notice-info/-warning/-critical/-success
                                  variantes de couleur d'accent de `.bevel-notice`
        .bevel-notice-icon        pictogramme optionnel du bandeau
        .bevel-notice-text        texte du bandeau de message
        .bevel-empty              état vide affiché dans une carte
        .bevel-empty-hint         ligne d'explication secondaire de `.bevel-empty`

    Cette liste doit rester synchronisée avec les classes réellement émises par
    `charts.kpi_card` et `ui.card` : une classe utilisée là-bas sans règle ici
    ne casse rien visiblement à l'import, mais rend l'élément à la taille par
    défaut du navigateur (un `<svg>` sans width/height tombe à 300x150px).

    Toujours dérivé de `active_tokens()` et jamais mis en cache : si
    l'utilisateur bascule clair/sombre depuis les réglages Streamlit, le
    prochain rerun doit repartir des bonnes couleurs plutôt que de garder un
    CSS figé au premier rendu.
    """
    st.markdown(css(), unsafe_allow_html=True)
    _inject_logo()


#: Monogramme de la navigation : un arc, écho de la jauge de forme, en
#: monochrome — lisible à 16 px, ce qu'aucun pictogramme détaillé ne survit.
_LOGO = Path(__file__).resolve().parent / "static" / "mark.svg"


def _inject_logo() -> None:
    """Pose `st.logo` sur la page courante.

    Streamlit n'attache PAS le logo à l'application mais à la page qui l'appelle :
    posé dans le seul fichier d'entrée, il disparaissait dès qu'on ouvrait
    « Progression » ou n'importe quelle autre page. Ici, il suit `inject_css()`,
    que chaque page appelle déjà en tête — et les pages futures l'auront sans
    avoir à y penser.
    """
    if _LOGO.exists():
        st.logo(str(_LOGO))


def css() -> str:
    """Le CSS lui-même, sans Streamlit autour.

    Séparé de `inject_css()` pour être VÉRIFIABLE : les tests du système visuel
    (échelle typographique, rayons, pas d'espacement) lisent cette chaîne. Un
    système figé qu'aucun test ne relit dérive au premier correctif pressé.
    """
    t = active_tokens()
    return f"""
        <style>
        /* Exposé en variable CSS parce que `ui.day_strip` doit pouvoir s'y
           référer depuis la règle qu'il émet lui-même (le contour
           d'aujourd'hui), sans jamais écrire de couleur en dur. */
        :root {{
            --bevel-accent: {t['accent']};
            /* Exposée pour `ui.day_strip`, qui émet une règle ciblée sur une
               date connue de lui seul : ce module ne peut pas la prévoir, mais
               il ne doit pas non plus laisser une couleur s'écrire ailleurs. */
            --bevel-border: {t['border']};
        }}

        [data-testid="stMetricValue"],
        .bevel-kpi,
        [data-testid="stDataFrame"] td,
        [data-testid="stTable"] td {{
            font-variant-numeric: tabular-nums;
        }}

        /* Rythme vertical de la page : UN seul intervalle entre blocs de premier
           niveau. Streamlit espace ses blocs selon un `gap` par défaut qui ne
           correspond à aucun échelon du barème, et les cartes paraissaient
           inégalement séparées sans qu'on puisse dire pourquoi. Avec le padding
           de carte figé à 24 px, la page se met à respirer régulièrement. */
        .stMainBlockContainer [data-testid="stVerticalBlock"] {{
            gap: 16px;
        }}

        /* Carte Bevel. Streamlit 1.60 n'expose plus de `data-testid` propre aux
           conteneurs bordés (`stVerticalBlockBorderWrapper` a disparu du bundle,
           le proto est passé à `flex_container.border` rendu par une classe
           emotion). On ancre donc sur le marqueur invisible que pose
           `ui.card()`, restreint au bloc PARENT IMMÉDIAT par le combinateur `>` :
           sans lui, `:has()` remonterait jusqu'au corps de page et
           transformerait toute la page en carte. */
        [data-testid="stVerticalBlock"]:has(
            > [data-testid="stElementContainer"] .bevel-card-marker
        ) {{
            background: {t['surface']};
            border: 1px solid {t['border']};
            border-radius: 12px;
            /* 24 px sur les quatre côtés, sans exception : un padding qui
               varie d'une carte à l'autre se lit comme un défaut d'alignement
               de la grille, pas comme une intention. */
            padding: 24px;
            /* Ancre du bouton d'aide, positionné en absolu sur la ligne du
               titre (cf. `st-key-cardhelp-`). */
            position: relative;
        }}
        /* Le marqueur ne doit occuper aucune place : on replie le conteneur
           d'élément que Streamlit enroule autour, pas seulement le span.

           Le test est « ce conteneur ne porte PAS de titre de carte », et non
           « le marqueur est fils unique » : le parseur HTML ferme le <p> que
           markdown ouvre autour du marqueur dès qu'il rencontre le <div> du
           titre, si bien que le marqueur se retrouve toujours seul dans son
           paragraphe. La règle `:only-child` masquait donc AUSSI le titre et
           sa pastille « i », sur toutes les pages. */
        [data-testid="stElementContainer"]:has(> [data-testid="stMarkdown"] .bevel-card-marker):not(:has(.bevel-card-title)) {{
            display: none;
        }}
        .bevel-card-marker {{
            display: none;
        }}
        /* Le marqueur est invisible, son PARAGRAPHE ne l'était pas.
           Streamlit rend l'en-tête de carte en markdown, ce qui enveloppe le
           marqueur dans un `<p>` et laisse un `<p></p>` vide derrière le titre.
           Ces deux paragraphes vides mesuraient 14 px : ils poussaient le titre
           vers le bas alors que le bouton « ? », positionné en absolu depuis le
           haut de la carte, ne bougeait pas — d'où les 17 px de décalage entre
           les deux, sur toutes les cartes de toutes les pages.
           Masquer le `<span>` ne suffisait pas ; c'est la boîte qui le porte
           qui doit disparaître. */
        [data-testid="stMarkdownContainer"] > p:has(> .bevel-card-marker) {{
            display: none;
        }}
        [data-testid="stMarkdownContainer"]:has(.bevel-card-title) > p:empty {{
            display: none;
        }}
        [data-testid="stVerticalBlock"]:has(> [data-testid="stElementContainer"] .bevel-card-marker) [data-testid="stPlotlyChart"] {{
            margin: 0;
        }}

        /* Les éléments d'une carte respirent d'un cran du barème, pas de trois :
           l'espacement par défaut de Streamlit laissait ~60 px entre les noms
           de zone et la courbe qu'ils précèdent. */
        [data-testid="stVerticalBlock"]:has(
            > [data-testid="stElementContainer"] .bevel-card-marker
        ) > [data-testid="stVerticalBlock"] {{
            gap: 8px;
        }}

        /* Surfaces internes : encarts posés SUR une carte (expanders du
           Glossaire, en-têtes de tableau) — d'où `surface_raised`. */
        /* Repli secondaire (« Détail chiffré ») : un LIEN, pas une barre grise
           pleine largeur. Une bande de 40 px qui traverse la carte pèse plus
           lourd que le contenu qu'elle cache, alors qu'on l'ouvre une fois par
           mois. Le fond de surface reste sur les expanders des pages de détail
           (Glossaire), où ils structurent tout le contenu. */
        [data-testid="stVerticalBlock"]:has(
            > [data-testid="stElementContainer"] .bevel-card-marker
        ) [data-testid="stExpander"] details {{
            background: transparent;
            border: none;
            border-radius: 0;
        }}
        [data-testid="stVerticalBlock"]:has(
            > [data-testid="stElementContainer"] .bevel-card-marker
        ) [data-testid="stExpander"] summary {{
            padding: 0;
            width: max-content;
            color: {t['ink_secondary']};
            font-size: 13px;
        }}
        [data-testid="stVerticalBlock"]:has(
            > [data-testid="stElementContainer"] .bevel-card-marker
        ) [data-testid="stExpander"] summary:hover {{
            color: {t['ink_primary']};
        }}
        [data-testid="stExpander"] details {{
            background: {t['surface_raised']};
            border: 1px solid {t['border']};
            border-radius: 8px;
        }}
        [data-testid="stDataFrame"] thead tr th {{
            background: {t['surface_raised']};
        }}

        h1 {{
            font-size: 22px;
            font-weight: 600;
            letter-spacing: -0.015em;
        }}
        h2 {{
            font-size: 15px;
            font-weight: 600;
            letter-spacing: -0.015em;
        }}
        h3 {{
            font-size: 13px;
            font-weight: 600;
            letter-spacing: -0.015em;
        }}

        hr {{
            opacity: 0.35;
        }}

        section[data-testid="stSidebar"] label {{
            color: {t['ink_secondary']};
        }}

        .bevel-kpi {{
            display: flex;
            flex-direction: column;
            gap: 4px;
            padding: 0 0 4px;
        }}
        /* Séparateurs de la grille de tuiles. Sans eux, la 2e rangée démarre
           juste sous les sparklines de la 1re et on ne sait plus quelle courbe
           appartient à quelle métrique. Le filet est posé sur la COLONNE
           Streamlit (`:has()`), seule maille qui existe entre les tuiles ;
           la première de chaque rangée n'en porte pas. */
        [data-testid="stColumn"]:has(> [data-testid="stVerticalBlock"] .bevel-kpi) {{
            border-left: 1px solid {t['border']};
            padding-left: 16px;
            padding-top: 12px;
            padding-bottom: 4px;
        }}
        [data-testid="stColumn"]:first-child:has(> [data-testid="stVerticalBlock"] .bevel-kpi) {{
            border-left: none;
            padding-left: 0;
        }}
        .bevel-kpi-top {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 8px;
        }}
        /* Le nom reste le point d'entrée par sa POSITION (en haut à gauche),
           pas par son poids : libellé discret en 0,8 rem / encre secondaire,
           valeur en 1,75 rem. Le rapport de taille passe de 1,7 à 2,2 — le
           chiffre se lit d'abord, le libellé confirme de quoi il s'agit. */
        .bevel-kpi-label {{
            color: {t['ink_secondary']};
            font-size: 13px;
            font-weight: 500;
            letter-spacing: 0;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }}
        /* 22 px, l'échelon en dessous du verdict : une tuile est une donnée de
           contexte, elle ne peut pas crier plus fort que la conclusion. Le
           barème n'a pas d'échelon entre 22 et 32 — c'est ce qui garantit
           qu'aucun élément ne vient se glisser à mi-chemin des deux. */
        .bevel-kpi-value {{
            color: {t['ink_primary']};
            font-size: 22px;
            font-weight: 600;
            line-height: 1.1;
            letter-spacing: -0.02em;
        }}
        .bevel-kpi-delta {{
            display: flex;
            align-items: center;
            gap: 8px;
            min-height: 1.4em;
        }}
        /* Pastille de variation : objet distinct de la valeur, pas une suite
           de texte coloré. Fond = la même couleur à 14 % d'opacité, posée en
           inline par `charts.kpi_card` (elle dépend du sens de la variation). */
        .bevel-kpi-pill {{
            display: inline-block;
            padding: 4px 8px;
            border-radius: 999px;
            font-size: 11px;
            font-weight: 500;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            max-width: 100%;
        }}
        /* viewBox 100x28 + preserveAspectRatio="none" : sans width/height
           explicites, le navigateur retomberait sur 300x150px et étirerait la
           courbe en un bloc distordu qui écrase la tuile. */
        .bevel-kpi-spark {{
            display: block;
            width: 100%;
            height: 34px;
            margin-top: 8px;
            overflow: visible;
            /* État de REPOS des trois formes. Défini ici et non en inline sur
               le SVG : une déclaration inline bat toute règle de feuille de
               style, et la bascule au survol (plus bas) ne pourrait alors
               jamais l'emporter. Les valeurs `*-cold`/`*-hot`, elles, sont
               posées sur la tuile par `charts.kpi_card` — elle seule connaît
               la couleur de la métrique. */
            --bevel-spark: var(--bevel-spark-cold);
            --bevel-spark-fill: var(--bevel-spark-cold-fill);
            --bevel-spark-dot: {t['ink_primary']};
        }}
        /* En-tête de graphe (`charts.chart_header_html`) : titre, note de
           contexte, légende — TROIS LIGNES EMPILÉES, en HTML, au-dessus de la
           figure Plotly.

           Elles vivaient dans la figure, où titre, sous-titre et légende visent
           tous la même bande au-dessus du plot : Plotly ne les empile pas et ne
           dimensionne aucune marge pour les annotations. Chaque correction était
           un décalage en coordonnées papier, à réajuster à la largeur de colonne
           suivante. Ici, c'est le navigateur qui empile, et deux blocs de flux
           normal ne peuvent pas se chevaucher. */
        .bevel-chart-head {{
            display: flex;
            flex-direction: column;
            gap: 4px;
            margin-bottom: 8px;
        }}
        /* Même corps que les nuances, mais 600 contre 400 : à 500, le cran était
           trop mince pour se lire sans comparer les deux côte à côte. */
        .bevel-chart-title {{
            color: {t['ink_primary']};
            font-size: 13px;
            font-weight: 600;
        }}
        .bevel-chart-note {{
            color: {t['ink_secondary']};
            font-size: 11px;
        }}
        /* Bornes min/max de la fenêtre affichée, sous la sparkline : sans
           elles, l'échelle automatique donne la même allure à une série qui
           varie de 2 % et à une qui double. */
        .bevel-kpi-scale {{
            display: flex;
            justify-content: space-between;
            gap: 8px;
            color: {t['ink_muted']};
            /* 0,7 rem et pas moins : sous cette taille, l'espace insécable qui
               sépare les milliers devient invisible et « 15 031 » se lit
               « 15031 ». La borne haute est en outre le dernier élément avant
               le bord de la carte, d'où le padding de sécurité. */
            font-size: 11px;
            line-height: 1;
            margin-top: 4px;
            padding-right: 4px;
        }}
        .bevel-kpi-scale span:last-child {{
            text-align: right;
        }}
        /* Les mots « min » et « max » : présents pour lever l'ambiguïté de
           position, mais un cran plus effacés que les nombres qu'ils qualifient
           — ce sont eux qu'on lit. */
        .bevel-kpi-scale i {{
            font-style: normal;
            opacity: 0.65;
        }}
        /* Pied de page : profondeur d'historique et dernier jour connu. Une
           mention de fiabilité, pas une donnée du jour — filet de séparation,
           alignement à droite (hors du chemin de lecture, qui part de la
           gauche) et l'encre la plus effacée du système. */
        .bevel-footer {{
            border-top: 1px solid {t['border']};
            margin-top: 32px;
            padding-top: 12px;
            text-align: right;
            color: {t['ink_muted']};
            font-size: 11px;
        }}

        /* --- Barre de temps par intensité -----------------------------------
           28 px et des extrémités arrondies : à 96 px de haut, la barre Plotly
           qu'elle remplace occupait la moitié de la carte pour trois nombres.
           La gouttière de 2 px sépare les segments sans filet — c'est la
           surface de la carte qui passe entre eux. */
        .bevel-effort {{
            margin-top: 16px;
        }}
        .bevel-effort-bar {{
            position: relative;
            display: flex;
            /* 2 px : une SÉPARATION, pas un espacement — même famille qu'un
               filet de 1 px, hors barème d'espacement pour la même raison.
               À 4 px, les segments d'une barre de 28 px cessent de se lire
               comme une seule barre et deviennent trois pastilles. */
            gap: 2px;
            height: 28px;
            border-radius: 999px;
            background: {t['grid']};
            overflow: hidden;
        }}
        .bevel-effort-seg {{
            display: flex;
            align-items: center;
            justify-content: center;
            min-width: 0;
            font-size: 11px;
            font-weight: 600;
            white-space: nowrap;
            overflow: hidden;
            /* Le survol éclaircit toute la rampe d'un coup : c'est la barre
               entière qui est un objet, pas chacun de ses segments. */
            transition: filter 160ms ease-out;
        }}
        /* Cible de survol : le BLOC entier, légende comprise, et non la seule
           barre. Une bande de 28 px est une cible étroite, et la légende fait
           partie du même objet. */
        .bevel-effort:hover .bevel-effort-seg {{
            filter: brightness(1.35);
        }}
        @media (prefers-reduced-motion: reduce) {{
            .bevel-effort-seg {{
                transition: none;
            }}
        }}
        /* Chevron de dépassement : la journée sort de l'échelle habituelle.
           Posé DANS la barre, sur sa dernière poignée de pixels, il se lit
           comme la continuation du dernier segment. */
        .bevel-effort-over {{
            position: absolute;
            right: 8px;
            top: 0;
            height: 28px;
            display: flex;
            align-items: center;
            color: {t['page']};
            font-size: 13px;
            font-weight: 600;
        }}
        /* Barre de référence : même axe, même rampe, 40 % d'opacité et 8 px de
           haut. Subordonnée en tout point — elle est le contexte de la barre du
           jour, pas une seconde mesure à lire pour elle-même. */
        .bevel-effort-ghost {{
            height: 8px;
            margin-top: 8px;
            opacity: 0.4;
        }}
        .bevel-effort-ref {{
            color: {t['ink_muted']};
            font-size: 11px;
            line-height: 1;
            margin-top: 4px;
        }}
        .bevel-effort-legend {{
            display: flex;
            flex-wrap: wrap;
            gap: 16px;
            margin-top: 16px;
            font-size: 11px;
            color: {t['ink_secondary']};
        }}
        .bevel-effort-key {{
            display: inline-flex;
            align-items: center;
            gap: 8px;
        }}
        /* Pastille CARRÉE : les segments qu'elle désigne sont des rectangles.
           Une pastille ronde renverrait à la bande de jours, qui code tout
           autre chose. */
        .bevel-effort-key i {{
            display: inline-block;
            width: 8px;
            height: 8px;
            border-radius: 0;
        }}
        .bevel-effort-key b {{
            color: {t['ink_primary']};
            font-weight: 600;
        }}
        /* Intitulé de groupe : la grille mélangeait effort et récupération sur
           deux rangées que rien ne distinguait. Capitales espacées en 11 px —
           ça structure sans ajouter de trait, et le poids reste sous celui des
           libellés de tuile pour ne pas concurrencer la lecture des chiffres. */
        .bevel-group {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            color: {t['ink_muted']};
            font-size: 11px;
            font-weight: 600;
            letter-spacing: 0.12em;
            text-transform: uppercase;
            margin: 0 0 8px;
        }}
        /* Légende du pointillé, au bout de la ligne d'intitulé : elle vaut pour
           les quatre tuiles de la rangée, elle se pose donc sur la seule ligne
           qui les couvre toutes. Ni capitales ni interlettrage — c'est une
           note, pas un intitulé. */
        .bevel-group-note {{
            display: inline-flex;
            align-items: center;
            gap: 4px;
            font-weight: 400;
            letter-spacing: 0;
            text-transform: none;
        }}
        .bevel-group-note i {{
            display: inline-block;
            width: 16px;
            border-top: 1px dashed {t['ink_muted']};
        }}
        /* Second groupe : il lui faut l'air que la première rangée prend
           naturellement sous le titre de la carte. */
        .bevel-group-gap {{
            margin-top: 24px;
        }}

        /* --- Survol d'une tuile : la courbe prend sa couleur -----------------
           Règle générale du tableau de bord : gris au repos, couleur au survol.
           La teinte est celle de la métrique dans les graphes de série des
           autres pages, donc une couleur y désigne toujours la même grandeur.

           Le budget de deux éléments colorés simultanés tient : le survol ne
           touche qu'une tuile, il est provoqué par l'utilisateur, et il s'en va
           avec le curseur. C'est de la couleur EXPLORATOIRE, pas de la couleur
           d'état — elle ne juge rien, elle désigne.

           L'état de repos est déclaré dans `.bevel-kpi-spark` plus haut. */
        .bevel-kpi:hover .bevel-kpi-spark {{
            --bevel-spark: var(--bevel-spark-hot);
            --bevel-spark-fill: var(--bevel-spark-hot-fill);
            --bevel-spark-dot: var(--bevel-spark-hot);
        }}
        /* La transition porte sur les formes et non sur les variables : une
           propriété personnalisée bascule d'un coup, elle ne s'interpole pas. */
        .bevel-spark-line, .bevel-spark-dot {{
            transition: stroke 160ms ease-out;
        }}
        .bevel-spark-fill {{
            transition: fill 160ms ease-out;
        }}
        @media (prefers-reduced-motion: reduce) {{
            .bevel-spark-line, .bevel-spark-dot, .bevel-spark-fill {{
                transition: none;
            }}
        }}
        .bevel-dot {{
            display: inline-block;
            flex: 0 0 auto;
            width: 8px;
            height: 8px;
            border-radius: 50%;
        }}
        /* Marqueur de statut : forme + couleur (cf. charts.STATUS_GLYPHS).
           `cursor: help` parce qu'il porte le libellé du statut en `title`. */
        /* 12 px et pas 0,72 rem : sous cette taille, un triangle se réduit à
           un accent et cesse d'être identifiable comme un marqueur. */
        .bevel-flag {{
            flex: 0 0 auto;
            font-size: 13px;
            line-height: 1;
            cursor: help;
        }}
        /* Titre de carte : du TEXTE, rien d'autre. Pas de fond, pas de
           bordure, pas de conteneur — le filet sous la ligne suffit à séparer
           l'en-tête du contenu, pour 1 px au lieu de 90. La réserve à droite
           laisse passer le bouton d'aide, qui est hors flux. */
        .bevel-card-title {{
            color: {t['ink_primary']};
            font-size: 15px;
            font-weight: 600;
            letter-spacing: -0.015em;
            line-height: 24px;
            padding-right: 32px;
            padding-bottom: 8px;
            margin-bottom: 16px;
            border-bottom: 1px solid {t['border']};
        }}
        /* Une légende sous le titre se pose sous le filet, pas entre les deux :
           elle appartient au contenu, pas à l'en-tête. */
        .bevel-card-title:has(+ .bevel-card-caption) {{
            padding-bottom: 4px;
            margin-bottom: 0;
            border-bottom: none;
        }}
        /* Verdict du jour : la SEULE affirmation d'état de la page. Tout ce qui
           est sous lui le nuance, rien ne le contredit — d'où le rapport de
           taille (22 px contre 13) qui interdit de lire une nuance comme un
           second verdict. */
        .bevel-verdict {{
            display: flex;
            flex-direction: column;
            gap: 8px;
        }}
        /* Le VERDICT est la plus grosse chose de la page — 32 px, l'échelon
           que les tuiles occupaient. La page posait une question, « je suis en
           forme ou pas ? », et sa réponse s'affichait plus petit que huit
           chiffres secondaires : « Frais » en 22 px sous « 2 459 kcal » en
           32 px. Le centre de gravité était sur les tuiles. */
        .bevel-verdict-headline {{
            display: flex;
            align-items: baseline;
            gap: 12px;
            color: {t['ink_primary']};
            font-size: 32px;
            /* 700 : la seule affirmation d'état de la page. Les tuiles partagent
               son échelon supérieur mais pas sa graisse. */
            font-weight: 700;
            letter-spacing: -0.02em;
            line-height: 1.2;
        }}
        /* Le score à la MÊME taille que la phrase : c'est le chiffre du
           verdict, pas une note de bas de page. Il s'efface par l'OPACITÉ et
           non par la taille — le rapport de poids se lit alors sans que le
           chiffre change de rang typographique. */
        .bevel-verdict-score {{
            color: {t['ink_primary']};
            opacity: 0.45;
            font-size: 32px;
            font-weight: 500;
            letter-spacing: -0.02em;
        }}
        /* Verdict NON CONCLUANT : un cran plus bas, à l'échelon « verdict » de
           l'échelle (22 px) plutôt qu'à celui des métriques (32 px). Le poids
           typographique doit suivre le contenu informationnel, pas la position
           dans le gabarit — « Rien de mesurable » est une non-réponse assumée,
           et l'écrire au corps réservé aux affirmations d'état lui donnait
           l'autorité d'une conclusion qu'elle refuse justement de tirer.
           Le jour où une pente conclut, le verdict retrouve ses 32 px : le
           changement de corps devient lui-même une information. */
        .bevel-verdict-headline.bevel-verdict-soft {{
            font-size: 22px;
        }}
        /* 15 px et non 13 : le hint, les nuances et le titre de graphe interne
           se retrouvaient tous les trois au même corps, ce qui aplatissait la
           hiérarchie et obligeait à LIRE pour comprendre la structure. Le hint
           remonte d'un cran — il commente le verdict, les nuances le nuancent :
           ce ne sont pas deux niveaux, ce sont trois. */
        .bevel-verdict-hint {{
            color: {t['ink_secondary']};
            font-size: 15px;
        }}
        .bevel-nuance {{
            display: flex;
            align-items: baseline;
            gap: 8px;
            color: {t['ink_secondary']};
            font-size: 13px;
            margin-top: 4px;
        }}
        /* Constat de NIVEAU, sous les nuances et séparé d'elles par un filet :
           ce qui s'écrit ici n'a pas été testé et ne doit pas se lire comme une
           nuance de plus. Un déplacement chiffré (« 35,1 → 28,2 ») est une
           soustraction, pas une inférence ; il mérite d'être dit, mais dans un
           registre visiblement autre. */
        .bevel-verdict-aside {{
            border-top: 1px solid {t['border']};
            margin-top: 12px;
            padding-top: 12px;
            color: {t['ink_secondary']};
            font-size: 13px;
        }}
        /* La ligne de constat AU MÊME CORPS que les nuances : c'est un troisième
           registre à côté du verdict et des nuances, pas une note de bas de
           carte. Elle portait pourtant la seule information réelle de la carte —
           une baisse de fond de 18 % — sous une phrase de 32 px annonçant qu'il
           ne se passe rien. */
        .bevel-verdict-aside-line {{
            display: flex;
            align-items: center;
            gap: 8px;
            flex-wrap: wrap;
        }}
        .bevel-verdict-aside b {{
            color: {t['ink_primary']};
            font-weight: 500;
        }}
        /* L'écart en teinte d'IDENTITÉ de la métrique, jamais en couleur de
           statut : il dit de quelle courbe on parle, il ne juge pas. Le budget
           de statut reste intact. */
        .bevel-aside-delta {{
            font-weight: 500;
            font-variant-numeric: tabular-nums;
        }}
        .bevel-aside-spark {{
            display: inline-flex;
            align-items: center;
            opacity: 0.75;
        }}
        /* La raison de l'exclusion, en encre la plus effacée : elle répond à une
           question qu'on ne se pose qu'une fois (« pourquoi le fond n'est-il pas
           dans le verdict ? »), mais il faut qu'elle soit à l'écran quand on se
           la pose — dans le « ? », personne ne l'a jamais trouvée. */
        .bevel-verdict-aside i {{
            display: block;
            margin-top: 4px;
            color: {t['ink_muted']};
            font-size: 11px;
            font-style: normal;
        }}

        /* Réglette de forme (`charts.form_rail`). Une barre de 6 px : la
           position se lit de gauche à droite, chaque zone porte son nom
           dessous, et le curseur — seul objet plein — dit où l'on est. Le
           repère fantôme, creux, dit d'où l'on vient. */
        .bevel-rail {{
            display: flex;
            flex-direction: column;
            gap: 8px;
            margin: 4px 0 16px;
        }}
        .bevel-rail-track {{
            position: relative;
            height: 6px;
        }}
        /* Les paliers dans leur propre boîte : elle porte l'arrondi et rogne
           les extrémités, ce qui évite d'avoir à désigner « le dernier palier »
           parmi des enfants dont le nombre change avec les repères.
           Le filet de 1 px entre paliers est ce qui rend quatre zones lisibles
           là où deux familles de teintes n'en montraient que deux. */
        .bevel-rail-zones {{
            display: flex;
            gap: 1px;
            height: 100%;
            border-radius: 999px;
            overflow: hidden;
        }}
        .bevel-rail-zone {{
            height: 100%;
        }}
        /* Nom du repère fantôme, dans sa propre rangée SOUS les noms de zone :
           superposé à eux, il tombait au hasard sur l'un des quatre. */
        .bevel-rail-notes {{
            position: relative;
            height: 12px;
        }}
        .bevel-rail-ghost-label {{
            position: absolute;
            top: 0;
            transform: translateX(-50%);
            white-space: nowrap;
            color: {t['ink_muted']};
            font-size: 11px;
            line-height: 1;
        }}
        .bevel-rail-cursor {{
            position: absolute;
            top: 50%;
            width: 12px;
            height: 12px;
            margin-left: -6px;
            border-radius: 50%;
            transform: translateY(-50%);
            box-shadow: 0 0 0 3px {t['surface']};
        }}
        .bevel-rail-ghost {{
            position: absolute;
            top: 50%;
            width: 8px;
            height: 8px;
            margin-left: -4px;
            border: 1px solid {t['ink_secondary']};
            border-radius: 50%;
            background: {t['surface']};
            transform: translateY(-50%);
            cursor: help;
        }}
        .bevel-rail-labels {{
            display: flex;
            color: {t['ink_muted']};
            font-size: 11px;
            line-height: 1;
        }}

        .bevel-card-caption {{
            color: {t['ink_secondary']};
            font-size: 13px;
        }}

        /* Bouton « ? » d'aide en tête de carte (`ui.card(info=...)`) : une
           invitation discrète, jamais une action de même poids que le contenu
           qu'il explique. Ciblé par la clé de conteneur posée dans
           `ui._help_popover` — la règle générique `[data-testid="stPopover"]`
           rabotait aussi le sélecteur de date de l'en-tête, qui se retrouvait
           4 px plus haut que les boutons voisins. */
        /* Hors flux, sur la ligne de base du titre (24 px de line-height, même
           hauteur que le bouton) : il ne consomme aucune hauteur de carte et
           ne peut plus décaler le titre. */
        /* Le repère du positionnement absolu doit être la CARTE, pas un
           conteneur intermédiaire : si Streamlit positionne lui-même le bloc
           qui enveloppe le popover, le bouton retomberait sous le titre au
           lieu de venir sur sa ligne. */
        [data-testid="stElementContainer"]:has(> [class*="st-key-cardhelp-"]) {{
            position: static;
        }}
        [class*="st-key-cardhelp-"] {{
            position: absolute;
            top: 24px;
            right: 24px;
            width: 24px;
            z-index: 2;
        }}
        [class*="st-key-cardhelp-"] button {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 24px;
            min-width: 24px;
            height: 24px;
            min-height: 24px;
            padding: 0;
            background: transparent;
            border: none;
            border-radius: 8px;
            color: {t['ink_muted']};
            font-size: 13px;
            line-height: 1;
        }}
        [class*="st-key-cardhelp-"] button:hover,
        [class*="st-key-cardhelp-"] button:focus {{
            background: {_rgba(t['ink_primary'], 0.06)};
            border: none;
            color: {t['ink_secondary']};
        }}
        /* Un seul signe : Streamlit ajoute son propre chevron à côté du
           libellé du popover, ce qui donnait « ? ⌄ » — deux glyphes pour une
           seule affordance. */
        [class*="st-key-cardhelp-"] button svg,
        [class*="st-key-cardhelp-"] button [data-testid="stIconMaterial"] {{
            display: none;
        }}

        /* Bloc de date : ‹ samedi 25 juillet 2026 ›, compact et centré.
           Les colonnes Streamlit occupent par défaut une fraction fixe de la
           largeur (`flex: 1 1 0`), ce qui envoyait les flèches à 100 px du
           texte qu'elles commandent — plus rien ne disait qu'elles agissaient
           sur cette date-là. Passées en largeur de contenu, elles s'y collent
           à 8 px. */
        [class*="st-key-dayhead-nav"] [data-testid="stHorizontalBlock"] {{
            align-items: center;
            justify-content: center;
            gap: 8px;
        }}
        [class*="st-key-dayhead-nav"] [data-testid="stColumn"] {{
            flex: 0 0 auto;
            width: auto;
            min-width: 0;
        }}
        [class*="st-key-dayhead-nav"] button {{
            min-height: 32px;
        }}
        /* MESURÉ, pas deviné : Streamlit pose `margin-bottom: -13px` sur
           `stMarkdownContainer`. La boîte de LAYOUT du bloc de texte fait donc
           13 px de moins que la boîte PEINTE, et `vertical_alignment="center"`
           centre consciencieusement la première — ce qui laisse le texte 6,5 px
           sous les boutons voisins. Aucun réglage d'alignement ne pouvait
           corriger ça, puisque l'alignement était déjà correct : c'est la boîte
           qui mentait. */
        [class*="st-key-dayhead-nav"] [data-testid="stMarkdownContainer"] {{
            margin-bottom: 0;
        }}
        .bevel-dayhead {{
            line-height: 32px;
            white-space: nowrap;
        }}
        /* En-tête des pages de série (`common.page_head`) : même correction de
           boîte que la barre du Bilan, et le même rythme vertical. Un
           `st.columns` nu se collait au bord supérieur de la page et son titre
           retombait sous le contrôle voisin, pour la raison mesurée ci-dessus.
           La règle est ici plutôt que dupliquée par page. */
        [class*="st-key-pagehead"] {{
            margin-bottom: 16px;
        }}
        [class*="st-key-pagehead"] [data-testid="stMarkdownContainer"] {{
            margin-bottom: 0;
        }}
        /* Le contrôle de droite aligné sur le BORD droit : centré, il flottait
           au milieu d'une colonne vide et ne se rattachait visuellement à rien. */
        [class*="st-key-pagehead"] [data-testid="stColumn"]:last-child
        [data-testid="stElementContainer"] {{
            display: flex;
            justify-content: flex-end;
        }}
        /* Le sélecteur de date : un bouton comme les autres de cette barre.
           Sans hauteur imposée, un popover est plus bas qu'un bouton. */
        [class*="st-key-dayhead-nav"] [data-testid="stPopover"] button {{
            min-height: 32px;
        }}
        /* Le badge de couverture dans son propre conteneur, avec ses marges :
           posé en markdown nu sous la barre, il chevauchait la bande de jours
           qui le suit. `text-align` et non `flex` : Streamlit donne 100 % de
           largeur au conteneur d'élément, qui absorbait donc tout le centrage
           du parent et laissait la pastille collée à gauche. */
        [class*="st-key-dayhead-badge"] {{
            margin: 4px 0 16px;
            text-align: center;
        }}
        /* Le centrage doit être posé sur le conteneur de markdown ET sur le
           `<p>` : tous deux déclarent `text-align: left`, et une déclaration
           explicite sur un descendant bat toujours une valeur héritée du
           parent. C'est pour ça que la pastille restait collée à gauche. */
        [class*="st-key-dayhead-badge"] [data-testid="stMarkdownContainer"],
        [class*="st-key-dayhead-badge"] [data-testid="stMarkdownContainer"] p {{
            text-align: center;
        }}
        /* Les deux flèches portent une icône Material, dont Streamlit fixe la
           couleur ; le libellé vide ne doit pas réserver de place. */
        [class*="st-key-day-prev"] button p,
        [class*="st-key-day-next"] button p {{
            display: none;
        }}
        [class*="st-key-dayhead-nav"] [data-testid="stPopover"] button p {{
            color: inherit;
        }}
        /* Anneau de focus vert sur la flèche après un clic : Streamlit le
           dessine avec sa couleur primaire, ce qui laissait une flèche
           encadrée d'accent en permanence. Conservé au clavier
           (`:focus-visible`), où il est la seule indication de position. */
        [class*="st-key-day-prev"] button:focus:not(:focus-visible),
        [class*="st-key-day-next"] button:focus:not(:focus-visible),
        [class*="st-key-daystrip-"] button:focus:not(:focus-visible) {{
            box-shadow: none;
            outline: none;
        }}
        /* Les deux flèches : carrées, discrètes, sans bordure. Ce sont des
           satellites du titre, pas des actions à part entière. */
        [class*="st-key-day-prev"] button,
        [class*="st-key-day-next"] button {{
            width: 32px;
            min-width: 32px;
            padding: 0;
            background: transparent;
            border-color: transparent;
            color: {t['ink_secondary']};
        }}
        [class*="st-key-day-prev"] button:hover,
        [class*="st-key-day-next"] button:hover {{
            background: {_rgba(t['ink_primary'], 0.06)};
            border-color: transparent;
            color: {t['ink_primary']};
        }}
        /* Flèche en bout de course : Streamlit redonne fond et bordure à un
           bouton désactivé, ce qui rendait la flèche INACTIVE plus visible que
           l'active — l'inverse de ce qu'elle doit dire. */
        [class*="st-key-day-prev"] button:disabled,
        [class*="st-key-day-next"] button:disabled {{
            background: transparent;
            border-color: transparent;
            color: {t['ink_muted']};
            opacity: 0.4;
        }}

        /* En-tête du jour sélectionné (page Aujourd'hui). */
        .bevel-dayhead {{
            display: flex;
            align-items: center;
            gap: 12px;
            flex-wrap: wrap;
        }}
        .bevel-daydate {{
            color: {t['ink_primary']};
            font-size: 15px;
            font-weight: 600;
            letter-spacing: -0.015em;
        }}
        /* Titre d'une page de série : le cran au-dessus de la date du Bilan.
           Les deux partagent `.bevel-daydate` (couleur, graisse, chasse) et ne
           divergent que par la taille — 22 px, l'échelon du verdict. Seule en
           haut à gauche, une question à 15 px se lit comme un intitulé de
           section ; sur le Bilan, la date reste à 15 px parce qu'elle tient le
           centre d'une barre de boutons de 32 px qui lui donne son poids. */
        .bevel-pagetitle {{
            font-size: 22px;
            letter-spacing: -0.02em;
        }}
        .bevel-daymeta {{
            color: {t['ink_secondary']};
            font-size: 13px;
        }}

        /* Badge de couverture : il ne se pose PLUS sur la ligne du titre, où
           il se lisait comme une précision de date. Sous la date, en ambre
           tinté, il se lit pour ce qu'il est — un avertissement sur la
           fiabilité de tout ce qui suit. */
        /* Il peut y en avoir DEUX (couverture partielle, appareil en
           calibration) : ils se suivent sur la même ligne, séparés par leur
           marge, et se replient l'un sous l'autre s'il n'y a pas la place. */
        .bevel-badge + .bevel-badge {{
            margin-left: 8px;
        }}
        .bevel-badge {{
            display: inline-flex;
            align-items: center;
            gap: 8px;
            margin-top: 4px;
            padding: 4px 8px;
            border-radius: 999px;
            background: {_rgba(t['status']['warning'], 0.12)};
            color: {t['status']['warning']};
            font-size: 11px;
        }}
        .bevel-badge-dot {{
            display: inline-block;
            flex: 0 0 auto;
            width: 8px;
            height: 8px;
            border-radius: 50%;
        }}

        /* Bande de 14 jours : le sélecteur de date principal.

           TROIS états, trois traitements — c'est ce qui manquait : le jour
           sélectionné et aujourd'hui se ressemblaient, si bien qu'une fois
           parti dans le passé, plus rien ne disait d'où l'on venait.
             sélectionné  fond d'accent plein
             aujourd'hui  contour d'accent (règle émise par `ui.day_strip`,
                          qui seul connaît la date du jour)
             normal       fond discret, uniforme */
        .bevel-daystrip-dotwrap {{
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 4px;
            margin-bottom: 4px;
        }}
        /* Initiales des jours : en `ink_muted` à 0,62 rem, elles étaient sous
           le seuil de lisibilité alors qu'elles portent la structure de la
           semaine (où tombent les week-ends). */
        .bevel-daystrip-weekday {{
            color: {t['ink_secondary']};
            font-size: 11px;
            line-height: 1;
            text-transform: uppercase;
        }}
        .bevel-daystrip-dot {{
            display: block;
            width: 8px;
            height: 8px;
            border-radius: 50%;
        }}
        .bevel-daystrip-label {{
            color: {t['ink_secondary']};
            font-size: 11px;
            text-align: center;
        }}
        /* État NORMAL. Couleur de texte posée explicitement : sans elle,
           Streamlit teinte le libellé de certains boutons avec sa couleur
           primaire (survol, focus, état actif), et les quatorze numéros
           n'avaient plus tous la même encre. */
        [class*="st-key-daystrip-"] button {{
            width: 100%;
            padding: 4px 0;
            min-height: 32px;
            font-size: 13px;
            font-weight: 500;
            background: {_rgba(t['ink_primary'], 0.04)};
            border-color: transparent;
            border-radius: 8px;
            color: {t['ink_secondary']};
        }}
        [class*="st-key-daystrip-"] button:hover {{
            background: {_rgba(t['ink_primary'], 0.10)};
            border-color: transparent;
            color: {t['ink_primary']};
        }}
        /* LA cause des quatorze numéros de couleurs différentes : Streamlit
           rend le libellé d'un bouton en markdown, dans un `<p>` qui porte sa
           propre couleur et ignore donc celle du bouton. Poser la couleur sur
           le bouton ne suffisait pas — il faut la faire hériter. */
        [class*="st-key-daystrip-"] button p,
        [class*="st-key-day-prev"] button p,
        [class*="st-key-day-next"] button p {{
            color: inherit;
        }}
        /* État SÉLECTIONNÉ : fond d'accent plein. Le rayon est celui de tous
           les autres — seul le fond change, jamais la forme. */
        [class*="st-key-daystrip-"] button[kind="primary"],
        [class*="st-key-daystrip-"] button[kind="primary"]:hover,
        [class*="st-key-daystrip-"] button[kind="primary"]:focus {{
            background: {t['accent']};
            border-color: {t['accent']};
            border-radius: 8px;
            color: {t['page']};
            font-weight: 600;
        }}
        /* --- Barre latérale -------------------------------------------------
           Sélecteurs relevés sur le DOM réel (`stSidebarLogo`, `stSidebarNavLink`)
           et non devinés : Streamlit ne documente pas ces `data-testid`, mais ils
           sont stables d'une version mineure à l'autre. */

        /* La marque : 28 px, décollée du bord, et son NOM à côté. Un
           pictogramme seul ne dit rien tant que la marque n'est pas connue —
           et il l'était d'autant moins qu'il touchait le haut du cadre. Le nom
           est écrit en CSS plutôt que dans le SVG : rendu en <img>, un texte
           SVG n'a pas accès à la police de la page et serait tombé sur une
           fonte système, à côté de tout le reste de l'interface. */
        [data-testid="stSidebarHeader"] {{
            display: flex;
            align-items: center;
            gap: 12px;
            padding-top: 24px;
        }}
        [data-testid="stSidebarLogo"] {{
            height: 28px;
            width: auto;
            margin: 0;
        }}
        [data-testid="stSidebarHeader"]::before {{
            content: "Santé";
            order: 2;
            color: {t['ink_primary']};
            /* 15 px et non 14 : le barème typographique est fermé (32/22/15/
               13/11) et le nom de l'app est un titre. Ouvrir une sixième
               taille pour un seul mot, c'est rouvrir l'échelle. */
            font-size: 15px;
            font-weight: 600;
            letter-spacing: -0.015em;
        }}
        [data-testid="stSidebarCollapseButton"] {{
            order: 3;
            margin-left: auto;
        }}

        /* État actif de la navigation : un filet d'accent, pas une pilule
           grise. La pilule pesait autant qu'un bouton d'action pour signaler
           une position ; deux pixels et un contraste de texte le disent aussi
           bien, et laissent la liste se lire comme une liste. */
        [data-testid="stSidebarNavLink"] {{
            background: transparent;
            border-radius: 0;
            border-left: 2px solid transparent;
            color: {_rgba(t['ink_primary'], 0.55)};
        }}
        [data-testid="stSidebarNavLink"]:hover {{
            background: transparent;
            color: {t['ink_primary']};
        }}
        [data-testid="stSidebarNavLink"][aria-current="page"] {{
            background: transparent;
            border-left-color: {t['accent']};
            color: {t['ink_primary']};
        }}
        /* Le libellé est un bloc markdown, avec sa propre couleur : sans
           héritage explicite, la couleur posée sur le lien n'atteint jamais le
           texte (même cause que les numéros de la bande de jours). */
        [data-testid="stSidebarNavLink"] [data-testid="stMarkdownContainer"],
        [data-testid="stSidebarNavLink"] p {{
            color: inherit;
        }}

        /* Fenêtre de comparaison : contrôle segmenté d'une ligne, et la période
           personnalisée en LIEN replié — une boîte encadrée pour une option
           qu'on n'ouvre presque jamais pesait plus lourd que le sélecteur
           lui-même. Même traitement que « Détail chiffré » dans les cartes :
           un motif, une seule apparence. */
        [data-testid="stSidebarUserContent"] h3 {{
            margin-bottom: 8px;
        }}
        [data-testid="stSidebarUserContent"] [data-testid="stExpander"] details {{
            background: transparent;
            border: none;
            border-radius: 0;
        }}
        [data-testid="stSidebarUserContent"] [data-testid="stExpander"] summary {{
            padding: 0;
            width: max-content;
            color: {t['ink_muted']};
            font-size: 13px;
        }}
        [data-testid="stSidebarUserContent"] [data-testid="stExpander"] summary:hover {{
            color: {t['ink_primary']};
        }}

        /* Bandeaux de message fermables. Accent + fond tinté à gauche,
           couleur dérivée de active_tokens() (jamais de hex en dur ici).

           Sémantique d'alerte figée, à ne pas élargir :
             AMBRE  = la donnée est incomplète ou non fiable (journée
                      partielle, appareil en calibration). Ne dit RIEN de
                      l'état du corps.
             ROUGE  = signal physiologique, et rien d'autre.
             NEUTRE = conseil chiffré (volume, dérive de FC de repos) : c'est
                      une information, pas une alarme, et le verdict porte
                      déjà la couleur du jour. */
        .bevel-notice {{
            display: flex;
            align-items: flex-start;
            gap: 8px;
            padding: 12px;
            border-radius: 8px;
            border-left: 3px solid;
            margin-bottom: 8px;
        }}
        .bevel-notice-info {{
            border-left-color: {t['ink_muted']};
            background: {_rgba(t['ink_muted'], 0.10)};
        }}
        .bevel-notice-warning {{
            border-left-color: {t['status']['warning']};
            background: {_rgba(t['status']['warning'], 0.10)};
        }}
        .bevel-notice-critical {{
            border-left-color: {t['status']['critical']};
            background: {_rgba(t['status']['critical'], 0.10)};
        }}
        .bevel-notice-success {{
            border-left-color: {t['status']['good']};
            background: {_rgba(t['status']['good'], 0.10)};
        }}
        /* Pictogramme optionnel d'un bandeau : aligné sur la première ligne
           du texte, à sa taille. Sans règle, il tombait à la taille par
           défaut du navigateur et déséquilibrait le bandeau. */
        .bevel-notice-icon {{
            flex: 0 0 auto;
            font-size: 13px;
            line-height: 1.4;
        }}
        .bevel-notice-text {{
            color: {t['ink_primary']};
            font-size: 13px;
            line-height: 1.4;
        }}
        /* Bouton « ✕ » des notices : discret, pas une action de même poids
           que le contenu du bandeau qu'il ferme. */
        [class*="st-key-notice-x-"] button {{
            background: transparent;
            border-color: transparent;
            color: {t['ink_muted']};
        }}

        /* État vide, affiché dans une carte à la place d'un graphe sans donnée. */
        .bevel-empty {{
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
            gap: 8px;
            min-height: 120px;
            padding: 24px 16px;
            color: {t['ink_muted']};
            text-align: center;
            border: 1px dashed {t['border']};
            border-radius: 8px;
        }}
        .bevel-empty-hint {{
            font-size: 11px;
            opacity: 0.85;
        }}
        </style>
        """

"""Le système visuel, figé et vérifié.

Un système qu'aucun test ne relit dérive au premier correctif pressé : une
taille « juste un peu plus grande » ici, un rayon arrondi là, et six mois plus
tard il n'y a plus de système du tout. Ces tests lisent la feuille de style
produite par `theme.css()` et refusent toute valeur hors barème.

Ils ne jugent PAS du goût — seulement de la cohérence : qu'il n'existe qu'une
échelle typographique, un pas d'espacement, trois rayons, et que la couleur
reste un budget et non un décor.
"""
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

import theme  # noqa: E402


@pytest.fixture(autouse=True)
def _dark(monkeypatch):
    monkeypatch.setattr(theme, "_detect_mode", lambda: "dark")
    yield


CSS = None


@pytest.fixture(autouse=True)
def _css():
    global CSS
    CSS = theme.css()
    yield


# --- Le barème --------------------------------------------------------------
TYPE_SCALE = {32, 22, 15, 13, 11}
SPACE_SCALE = {0, 4, 8, 12, 16, 24, 32}
RADII = {12, 8, 999}


def test_type_scale_has_exactly_five_steps():
    sizes = {int(v) for v in re.findall(r"font-size:\s*(\d+)px", CSS)}
    assert sizes <= TYPE_SCALE, f"tailles hors barème : {sorted(sizes - TYPE_SCALE)}"


def test_no_relative_font_sizes_survive():
    """Les `rem` suivent `baseFontSize` de config.toml : deux systèmes de
    tailles qui bougent l'un sans l'autre, c'est un système de moins."""
    assert not re.findall(r"font-size:\s*[\d.]+rem", CSS)


def test_spacing_uses_the_four_eight_scale():
    values = []
    for prop, val in re.findall(r"(padding|margin|gap)(?:-\w+)?:\s*([^;]+);", CSS):
        for token in val.split():
            m = re.fullmatch(r"(-?\d+)px", token)
            if m and int(m.group(1)) >= 0:  # les négatifs sont des chevauchements de bordure
                # Un `gap` de 1 ou 2 px est une SÉPARATION et non un
                # espacement : c'est la même famille qu'un filet de 1 px, qui
                # n'a jamais relevé du barème. Au-delà, il redevient de
                # l'espacement et doit rentrer dans le rang.
                if prop == "gap" and int(m.group(1)) <= 2:
                    continue
                values.append(int(m.group(1)))
    hors = sorted({v for v in values} - SPACE_SCALE)
    assert not hors, f"espacements hors barème : {hors}"


def test_radii_are_cards_controls_or_pills():
    radii = {r for r in re.findall(r"border-radius:\s*([^;]+);", CSS)}
    numeric = {int(m.group(1)) for r in radii if (m := re.fullmatch(r"(\d+)px", r.strip()))}
    other = {r.strip() for r in radii if not re.fullmatch(r"\d+px", r.strip())}
    # `0` est l'ABSENCE de rayon (on annule celui d'un composant Streamlit),
    # pas une quatrième valeur de barème.
    assert numeric <= RADII | {0}, f"rayons hors barème : {sorted(numeric - RADII - {0})}"
    # Formes composées : pastille ronde, et coins d'un segment de réglette.
    assert other <= {"50%", "0", "999px 0 0 999px", "0 999px 999px 0"}, (
        f"rayons non numériques inattendus : {other}"
    )


def test_every_bevel_class_used_in_the_app_has_a_rule():
    """Le garde-fou qui manquait.

    En supprimant une classe morte du CSS, une découpe trop large a emporté
    avec elle tout le bloc du verdict : la phrase la plus importante de la page
    s'est retrouvée sans style, et rien ne l'a signalé — les tests portaient sur
    le barème, pas sur la couverture. Ce test relie les deux côtés : toute
    classe `bevel-*` émise par le code doit exister dans la feuille de style.
    """
    app = Path(__file__).resolve().parent.parent / "app"
    used: set[str] = set()
    for path in [*app.glob("*.py"), *(app / "pages").glob("*.py")]:
        if path.name == "theme.py":
            continue
        # `(?<!-)` écarte les PROPRIÉTÉS PERSONNALISÉES (`--bevel-spark`,
        # `var(--bevel-accent)`) : elles portent le même préfixe que les classes
        # sans en être, et une liste d'exceptions à maintenir à la main les
        # aurait laissées passer une par une.
        used |= set(re.findall(r"(?<!-)bevel-[a-z0-9-]+", path.read_text(encoding="utf-8")))
    used -= {
        # Ancre `:has()` pour le CSS de carte, sans style propre.
        "bevel-card-marker",
        # Préfixe d'une classe construite à l'exécution (`bevel-notice-{kind}`) :
        # les variantes réelles sont vérifiées par les tests de sémantique.
        "bevel-notice-",
        # Idem pour les témoins de légende (`bevel-swatch-{kind}`) — leurs trois
        # variantes réelles sont vérifiées juste en dessous.
        "bevel-swatch-",
    }
    orphans = sorted(c for c in used if f".{c} " not in CSS and f".{c}," not in CSS
                     and f".{c}:" not in CSS and f".{c}{{" not in CSS)
    assert not orphans, f"classes sans règle CSS : {orphans}"


def test_every_legend_swatch_kind_has_its_rule():
    """`bevel-swatch-{kind}` est construite à l'exécution : le test de classes
    orphelines ne peut pas la voir, et une variante ajoutée sans règle rendrait
    un témoin de légende invisible."""
    import charts  # noqa: PLC0415 — importé ici, comme le reste du module
    for kind in charts.LEGEND_KINDS:
        assert f".bevel-swatch-{kind} " in CSS or f".bevel-swatch-{kind}{{" in CSS, kind


# --- Les jetons --------------------------------------------------------------
def test_surfaces_are_the_three_frozen_levels():
    assert theme.DARK["page"] == "#0A0A0B"
    assert theme.DARK["surface"] == "#101012"
    assert theme.DARK["surface_raised"] == "#17171A"
    assert theme.DARK["border"] == "rgba(255,255,255,0.06)"


@pytest.mark.parametrize("mode", ["dark", "light"])
def test_inks_are_neutral_greys_in_both_themes(monkeypatch, mode):
    """Les encres sont les opacités .92/.60/.38 aplaties : donc des gris purs.
    Une encre teintée rouvrirait une seconde famille de couleurs par la porte
    du texte."""
    monkeypatch.setattr(theme, "_detect_mode", lambda: mode)
    t = theme.active_tokens()
    for key in ("ink_primary", "ink_secondary", "ink_muted"):
        h = t[key].lstrip("#")
        r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
        assert max(r, g, b) - min(r, g, b) <= 2, f"{key} ({t[key]}) n'est pas un gris neutre"


def test_inks_are_ordered_from_primary_to_muted():
    def lum(hexa):
        h = hexa.lstrip("#")
        return sum(int(h[i:i + 2], 16) for i in (0, 2, 4))
    t = theme.DARK
    assert lum(t["ink_primary"]) > lum(t["ink_secondary"]) > lum(t["ink_muted"])


def test_the_chart_pair_is_reserved_and_distinct_from_status_colours():
    """Le duo bleu/orange n'existe que pour la courbe fond/fatigue. S'il
    croisait une couleur de statut, une série deviendrait un verdict."""
    for tokens in (theme.DARK, theme.LIGHT):
        assert len(tokens["chart_pair"]) == 2
        assert not set(tokens["chart_pair"]) & set(tokens["status"].values())


def test_config_toml_mirrors_the_dark_tokens():
    """TOML ne peut pas importer de Python : le miroir est manuel, donc il
    casse en silence. Ce test est le seul garde-fou."""
    config = (Path(__file__).resolve().parent.parent / ".streamlit" / "config.toml").read_text(encoding="utf-8")
    assert f'backgroundColor = "{theme.DARK["page"]}"' in config
    assert f'secondaryBackgroundColor = "{theme.DARK["surface"]}"' in config
    assert f'textColor = "{theme.DARK["ink_primary"]}"' in config
    assert f'primaryColor = "{theme.DARK["status"]["good"]}"' in config, (
        "l'accent unique de l'app est celui de la Forme"
    )


# --- La bande de jours : trois états distincts -------------------------------
def _rule(selector: str) -> str:
    """Corps de la première règle CSS dont le sélecteur contient `selector`.

    Le sélecteur doit être un membre EXACT de la liste de la règle. Une
    recherche textuelle attrapait `button:hover` ou `button p` en croyant
    tenir `button`, et l'assertion portait alors sur un corps qui n'était pas
    celui visé — deux de ces tests sont passés au vert pour cette raison avant
    d'être corrigés.
    """
    for block in re.finditer(r"([^{}]+)\{([^}]*)\}", CSS):
        parts = [p.strip() for p in block.group(1).split(",")]
        # La dernière entrée traîne le commentaire qui précède la règle.
        parts = [p.split("*/")[-1].strip() for p in parts]
        if selector in parts:
            return block.group(2)
    raise AssertionError(f"règle introuvable : {selector}")


def test_day_strip_states_are_visually_distinct():
    """Sélectionné, aujourd'hui et normal doivent se distinguer sans ambiguïté :
    confondre les deux premiers rend la bande inutilisable dès qu'on navigue
    dans le passé — plus rien ne dit d'où l'on vient."""
    t = theme.DARK
    normal = _rule('[class*="st-key-daystrip-"] button')
    selected = _rule('[class*="st-key-daystrip-"] button[kind="primary"]')
    assert t["accent"] in selected, "le jour choisi porte l'accent en fond plein"
    assert t["accent"] not in normal, "un jour ordinaire ne porte pas l'accent"
    # Aujourd'hui : contour, émis par `ui.day_strip` qui seul connaît la date.
    assert "--bevel-accent" in CSS, "la variable d'accent doit être exposée au module ui"


def test_day_strip_keeps_one_radius_for_every_state():
    radii = re.findall(r'st-key-daystrip-[^{]*\{[^}]*border-radius:\s*(\d+)px', CSS)
    assert radii and len(set(radii)) == 1, f"rayons différents selon l'état : {set(radii)}"


def test_day_strip_pins_its_label_colour():
    """Streamlit rend le libellé d'un bouton en markdown, dans un `<p>` qui
    porte sa propre couleur : poser la couleur sur le bouton ne suffit pas, il
    faut la faire hériter — sinon les quatorze numéros n'ont pas tous la même
    encre."""
    assert "color:" in _rule('[class*="st-key-daystrip-"] button')
    assert "color: inherit" in _rule('[class*="st-key-daystrip-"] button p')


# --- Le budget couleur -------------------------------------------------------
def test_no_categorical_colour_is_hardcoded_in_the_stylesheet():
    """La feuille de style ne porte que des surfaces, des encres et des
    statuts. Toute teinte catégorielle qui y apparaît est une couleur qui a
    échappé au budget."""
    for hexa in theme.DARK["categorical"]:
        if hexa in theme.DARK["status"].values():
            continue
        assert hexa.lower() not in CSS.lower(), f"{hexa} (catégorielle) écrit en dur dans le CSS"


def test_notice_variants_keep_amber_for_data_and_red_for_the_body():
    """Sémantique d'alerte : ambre = donnée incomplète, rouge = physiologique,
    neutre = conseil. Un bandeau d'information ne doit pas emprunter l'accent."""
    t = theme.DARK
    info = CSS.split(".bevel-notice-info")[1].split("}")[0]
    assert t["ink_muted"] in info, "le bandeau neutre doit rester en encre"
    warning = CSS.split(".bevel-notice-warning")[1].split("}")[0]
    assert t["status"]["warning"] in warning
    critical = CSS.split(".bevel-notice-critical")[1].split("}")[0]
    assert t["status"]["critical"] in critical


def test_hover_is_the_only_place_where_a_tile_takes_colour():
    """La règle générale du tableau de bord : gris au repos, couleur au survol.

    Elle ne dépense pas le budget de deux éléments colorés — le survol ne touche
    qu'une tuile, il est déclenché par l'utilisateur et il s'en va avec le
    curseur. Mais elle n'existe que si la bascule porte sur les TROIS formes de
    la sparkline : une courbe colorée au-dessus d'une aire restée grise se lit
    comme un défaut de rendu.
    """
    hover = _rule('.bevel-kpi:hover .bevel-kpi-spark')
    for var in ("--bevel-spark:", "--bevel-spark-fill:", "--bevel-spark-dot:"):
        assert var in hover, f"{var} n'est pas basculé au survol"
    rest = _rule(".bevel-kpi-spark")
    assert "--bevel-spark: var(--bevel-spark-cold)" in rest, (
        "l'état de repos doit être défini en feuille de style, pas en inline : "
        "une déclaration inline sur la tuile battrait la règle de survol"
    )


def test_group_labels_stay_below_the_tile_labels_in_weight():
    """Un intitulé de groupe structure, il ne se lit pas avant les chiffres."""
    group = _rule(".bevel-group")
    assert "font-size: 11px" in group and "uppercase" in group
    assert "letter-spacing" in group, "des capitales sans interlettrage sont illisibles"


def test_the_verdict_is_typographically_larger_than_any_tile():
    """La page pose une question — « je suis en forme ou pas ? ». Sa réponse ne
    peut pas s'afficher plus petit que huit chiffres de contexte. « Frais » en
    22 px sous « 2 459 kcal » en 32 px mettait le centre de gravité de la page
    sur les tuiles.
    """
    def size(selector: str) -> int:
        return int(re.search(r"font-size:\s*(\d+)px", _rule(selector)).group(1))
    verdict = size(".bevel-verdict-headline")
    assert verdict > size(".bevel-kpi-value")
    assert verdict == size(".bevel-verdict-score"), (
        "le score est le chiffre du verdict, pas une note de bas de page : "
        "il s'efface par l'opacité, jamais par la taille"
    )
    assert "opacity" in _rule(".bevel-verdict-score")

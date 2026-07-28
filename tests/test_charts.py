"""Tests des parties purement calculatoires de app/charts.py et app/theme.py.

Ne touche pas à la base réelle : uniquement les fonctions pures (conversion de
couleurs, résolution de statut, construction de grilles) et la structure des
`go.Figure` produites (formes ajoutées, valeurs des traces), pas le rendu.
`app/` n'est pas un package (pas de __init__.py, imports "plats" comme dans
les pages Streamlit) : on ajoute son dossier à sys.path, comme le font toutes
les pages.
"""
import math
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

import charts  # noqa: E402
import theme  # noqa: E402
from health import metrics  # noqa: E402
from health.metrics import Metric  # noqa: E402


@pytest.fixture(autouse=True)
def _force_light_theme(monkeypatch):
    """Sauf test explicite sur le sombre, fixe le thème pour des assertions
    stables (les jetons clairs/sombres partagent la structure mais pas les
    valeurs)."""
    monkeypatch.setattr(theme, "_detect_mode", lambda: "light")
    yield


def _metric(**overrides) -> Metric:
    base = dict(
        key="test_metric", label="Test", short="Test", unit=" u", family="forme",
        what="x" * 40, how_read="y" * 50, provenance="Calculé ici",
        direction=1, baseline="personal", ma_window=7,
    )
    base.update(overrides)
    return Metric(**base)


# --- theme.py -----------------------------------------------------------
def test_active_tokens_switches_with_detected_mode(monkeypatch):
    monkeypatch.setattr(theme, "_detect_mode", lambda: "dark")
    assert theme.active_tokens()["mode"] == "dark"
    assert theme.active_tokens()["surface"] == theme.DARK["surface"]
    monkeypatch.setattr(theme, "_detect_mode", lambda: "light")
    assert theme.active_tokens() == theme.LIGHT


# --- utilitaires internes de charts.py --------------------------------------
def test_with_opacity_converts_hex_to_rgba():
    assert charts._with_opacity("#2a78d6", 0.5) == "rgba(42,120,214,0.5)"


def test_ramp_to_colorscale_spans_zero_to_one():
    scale = charts._ramp_to_colorscale(["#111111", "#222222", "#333333"])
    assert scale[0][0] == 0
    assert scale[-1][0] == 1
    assert scale[1][0] == pytest.approx(0.5)


def test_sequential_scale_flips_anchor_in_dark_mode(monkeypatch):
    """cf. skill dataviz : la rampe séquentielle "flips anchor in dark" --
    proche-surface doit toujours être le premier élément, et la surface change
    de bout en bout entre les deux modes."""
    monkeypatch.setattr(theme, "_detect_mode", lambda: "light")
    light_scale = charts.sequential_scale()
    monkeypatch.setattr(theme, "_detect_mode", lambda: "dark")
    dark_scale = charts.sequential_scale()
    assert light_scale == list(reversed(dark_scale))


def test_diverging_colorscale_has_neutral_midpoint():
    scale = charts.diverging_colorscale()
    assert scale[1][0] == 0.5
    assert scale[1][1] == theme.active_tokens()["diverging_mid"]


# --- status_color ------------------------------------------------------------
def test_status_color_respects_higher_is_better():
    t = theme.active_tokens()
    assert charts.status_color(80, (50, 60, 70), higher_is_better=True) == t["status"]["good"]
    assert charts.status_color(40, (50, 60, 70), higher_is_better=True) == t["status"]["critical"]
    assert charts.status_color(None, (50, 60, 70)) == t["ink_muted"]


def test_status_color_flips_thresholds_when_lower_is_better():
    t = theme.active_tokens()
    # FC repos : plus bas = mieux -- thresholds décroissants avec higher_is_better=False.
    assert charts.status_color(55, (80, 70, 60), higher_is_better=False) == t["status"]["good"]
    assert charts.status_color(90, (80, 70, 60), higher_is_better=False) == t["status"]["critical"]


# --- résolution de statut pour kpi_card --------------------------------------
def test_status_key_for_metric_prefers_z_score_when_available():
    m = _metric(direction=1)
    assert charts._status_key_for_metric(m, 100, z=2.5) == "excellent"
    assert charts._status_key_for_metric(m, 100, z=-2.5) == "critical"


def test_status_key_for_metric_falls_back_to_good_range_without_z():
    m = _metric(baseline="fixed", good_range=(65, 100), direction=1)
    assert charts._status_key_for_metric(m, 90, z=None) == "good"
    assert charts._status_key_for_metric(m, 10, z=None) == "critical"


def test_status_key_for_metric_is_neutral_without_z_or_good_range():
    m = _metric(baseline="personal", good_range=None)
    assert charts._status_key_for_metric(m, 50, z=None) == "neutral"


# --- base_layout : pas de titre vide ----------------------------------------
def test_base_layout_omits_the_title_key_entirely_when_there_is_no_title():
    """`title=None` instancie quand même l'objet Title, sérialisé `"title": {}`,
    et Plotly.js écrit alors « undefined » au-dessus du graphe."""
    assert "title" not in charts.base_layout(None)
    assert charts.base_layout("Titre")["title"]["text"] == "Titre"


def test_figures_without_a_title_serialise_without_one():
    import json
    df = pd.DataFrame({"local_date": pd.date_range("2026-06-29", periods=28),
                       "ctl": [20.0] * 28, "atl": [18.0] * 28})
    layout = json.loads(charts.form_trend(df).to_json())["layout"]
    assert layout.get("title", {}) == {} or "text" in layout.get("title", {})
    assert layout.get("title", {}).get("text") is None


# --- axe de dates en français ------------------------------------------------
def test_fr_date_axis_writes_french_labels_with_the_year_only_once():
    dates = pd.date_range("2026-06-29", periods=28)
    fig = charts.fr_date_axis(go.Figure(), dates)
    labels = list(fig.layout.xaxis.ticktext)
    assert labels[0] == "29 juin 2026"
    assert all("juin" in x or "juil." in x for x in labels)
    assert sum("2026" in x for x in labels) == 1


def test_fr_date_axis_always_includes_the_last_day():
    dates = pd.date_range("2026-01-01", periods=10)
    fig = charts.fr_date_axis(go.Figure(), dates, max_ticks=3)
    assert fig.layout.xaxis.tickvals[-1] == pd.Timestamp("2026-01-10")


def test_fr_date_axis_is_a_noop_on_empty_dates():
    fig = charts.fr_date_axis(go.Figure(), [])
    assert fig.layout.xaxis.ticktext is None


# --- règle de couleur : gris par défaut, marqueur sur attention seulement ----
def test_only_adverse_statuses_get_a_marker():
    """Un marqueur vert permanent sur une métrique qui progresse (VO2max) ne
    hiérarchise plus rien : seuls les statuts défavorables sont marqués."""
    assert set(charts.ATTENTION_STATUSES) == {"critical", "serious"}
    assert "good" not in charts.ATTENTION_STATUSES
    assert "excellent" not in charts.ATTENTION_STATUSES


def test_sparkline_marks_the_last_point_and_draws_the_habitual_band():
    svg = charts._sparkline_svg(pd.Series([10.0, 12.0, 11.0, 14.0]), "#123456",
                                baseline=11.5, band=(10.0, 13.0))
    assert svg.count("<line") == 2, "une ligne de baseline + le point terminal"
    assert 'stroke-linecap="round"' in svg, "le point terminal est un segment à bouts ronds"
    assert "<rect" in svg, "la fourchette habituelle est une bande"


def test_sparkline_band_never_overflows_the_frame():
    """Une fourchette plus large que les données peindrait toute la tuile si
    elle n'était pas bornée au cadre."""
    svg = charts._sparkline_svg(pd.Series([10.0, 11.0]), "#123456", band=(-500.0, 500.0))
    rect = svg.split("<rect")[1]
    y = float(rect.split('y="')[1].split('"')[0])
    h = float(rect.split('height="')[1].split('"')[0])
    assert y >= 0 and y + h <= 34


def test_sparkline_stays_empty_on_a_series_too_short_to_draw():
    assert charts._sparkline_svg(pd.Series([1.0]), "#123456") == ""
    assert charts._sparkline_svg(None, "#123456") == ""


# --- jauge : zones nommées et repère de la veille -----------------------------
def test_gauge_names_its_zones_and_marks_the_previous_value():
    ranges = [(-20, -10, "critical"), (-10, -4, "serious"), (-4, 3, "good"), (3, 10, "excellent")]
    fig = charts.gauge(5, ranges, zone_labels={"critical": "Surchargé", "excellent": "Frais"},
                       previous=-6)
    texts = [a.text for a in fig.layout.annotations]
    assert "Surchargé" in texts and "Frais" in texts
    assert fig.data[0].gauge.threshold.value == pytest.approx(-6)


def test_gauge_zone_labels_skip_slivers_too_narrow_to_read():
    ranges = [(0, 99, "good"), (99, 100, "excellent")]
    fig = charts.gauge(50, ranges, zone_labels={"good": "Large", "excellent": "Étroit"})
    texts = [a.text for a in fig.layout.annotations]
    assert texts == ["Large"]


def test_gauge_clamps_a_previous_value_outside_the_axis():
    fig = charts.gauge(5, [(-10, 10, "good")], previous=999)
    assert fig.data[0].gauge.threshold.value == pytest.approx(10)


# --- effort_bar : la barre de temps par intensité ----------------------------
def _seg_widths(html_str: str) -> list[float]:
    return [float(chunk.split("flex:0 0 ")[1].split("%")[0])
            for chunk in html_str.split('class="bevel-effort-seg"')[1:]]


def test_effort_bar_puts_both_bars_on_one_shared_axis():
    """La barre de référence ne sert à rien si elle a son propre axe : deux
    répartitions de durées très différentes occuperaient alors la même largeur
    et se ressembleraient, ce qui est exactement l'inverse du but."""
    html_str = charts.effort_bar([("Modérée", 30.0)], [("Modérée", 10.0)], scale_max=60.0)
    day, ref = html_str.split("bevel-effort-ghost")
    assert _seg_widths(day) == [50.0], "30 min sur un axe de 60 = la moitié"
    assert _seg_widths("x" + ref) == [pytest.approx(16.6667, abs=1e-3)]


def test_effort_bar_axis_never_clips_the_day_it_draws():
    """Un jour record ne doit pas déborder de sa propre échelle."""
    html_str = charts.effort_bar([("Pic", 90.0)], scale_max=60.0)
    assert sum(_seg_widths(html_str)) == pytest.approx(100.0)


def _seg_texts(html_str: str) -> list[str]:
    """Contenu écrit DANS chaque segment (et non son `title` de survol)."""
    bar = html_str.split('class="bevel-effort-legend"')[0]
    return [chunk.split(">", 1)[1].split("</span>")[0]
            for chunk in bar.split('class="bevel-effort-seg"')[1:]]


def test_effort_bar_writes_the_duration_only_where_it_fits():
    """Sous ~10 % de la largeur, la durée déborde sur le segment voisin. La
    légende la porte de toute façon, pour tous les segments."""
    assert _seg_texts(charts.effort_bar([("Modérée", 95.0), ("Pic", 5.0)])) == ["1 h 35 min", ""]
    # Juste au-dessus du seuil, elle revient.
    assert _seg_texts(charts.effort_bar([("Modérée", 88.0), ("Pic", 12.0)])) == \
        ["1 h 28 min", "12 min"]


def test_effort_bar_ramp_is_one_hue_at_three_luminosities():
    """Trois teintes distinctes suggéreraient trois natures différentes là où
    il n'y a qu'une grandeur, graduée."""
    t = theme.active_tokens()
    html_str = charts.effort_bar([("Modérée", 10.0), ("Soutenue", 10.0), ("Pic", 10.0)])
    backgrounds = [c.split("background:")[1].split(";")[0]
                   for c in html_str.split('class="bevel-effort-seg"')[1:]]
    assert len(set(backgrounds)) == 3, "les trois segments doivent être distinguables"
    rgb = tuple(int(t["accent"].lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    for bg in backgrounds:
        assert f"{rgb[0]},{rgb[1]},{rgb[2]}" in bg.replace(" ", "") or bg == t["accent"]


def test_effort_bar_legend_names_and_times_every_zone_including_the_shortest():
    """Un segment d'une minute fait deux pixels : il ne peut rien porter, et
    c'est justement le plus notable de la journée."""
    html_str = charts.effort_bar([("Modérée", 60.0), ("Pic", 1.0)])
    legend = html_str.split('class="bevel-effort-legend"')[1]
    assert "Modérée" in legend and "Pic" in legend
    assert "1 min" in legend


def test_effort_bar_is_empty_when_there_is_nothing_to_draw():
    """Une barre de largeur nulle sur une piste vide prétendrait qu'il y a
    quelque chose à lire : c'est à l'appelant d'afficher un état vide."""
    assert charts.effort_bar([]) == ""
    assert charts.effort_bar([("Modérée", 0.0)]) == ""


def test_effort_bar_drops_the_reference_when_there_is_none():
    html_str = charts.effort_bar([("Modérée", 10.0)])
    assert "bevel-effort-ghost" not in html_str


# --- grouped_bars -----------------------------------------------------------
def test_grouped_bars_groups_instead_of_stacking():
    """Empiler répondrait « de quoi est faite la semaine ? » ; la question posée
    ici est « laquelle a bougé, et de combien ? »."""
    fig = charts.grouped_bars(
        ["Jambes", "Gainage"],
        [("Semaine passée", [30, 10]), ("Cette semaine", [45, 12])],
        y_title="minutes",
    )
    assert fig.layout.barmode == "group"
    assert len(fig.data) == 2


def test_grouped_bars_paints_the_reference_series_in_ink():
    """La première série est le PASSÉ : à couleur égale, plus rien ne dit
    laquelle des deux barres est le repère."""
    t = charts.theme.active_tokens()
    fig = charts.grouped_bars(
        ["Jambes"], [("Avant", [30]), ("Après", [45])],
    )
    assert fig.data[0].marker.color == t["ink_muted"]
    assert fig.data[1].marker.color == t["categorical"][0]


def test_grouped_bars_is_empty_when_there_is_nothing_to_compare():
    fig = charts.grouped_bars([], [], title="Titre")
    assert fig.layout.annotations[0].text == "Pas de quoi comparer sur cette période."


# --- pastille de variation et bornes de sparkline ------------------------
def test_kpi_tile_drops_the_pill_on_a_zero_delta(monkeypatch):
    """« 0 vs ta normale 28 j » occupe la place d'une variation pour dire qu'il
    n'y en a pas. La place reste RÉSERVÉE : sans elle, la sparkline d'une tuile
    sur quatre remonterait et la grille se lirait comme mal rendue."""
    m = _metric(fmt="{:.0f}")
    html_str = _render_kpi_html(monkeypatch, m, 6.0, prev=6.0)
    assert "vs moyenne" not in html_str
    assert "normale non calculable" not in html_str, "la normale existe : 6 vs 6"
    assert "visibility:hidden" in html_str


def test_kpi_tile_still_explains_a_missing_baseline(monkeypatch):
    """Écart nul et comparaison impossible donnent tous deux « pas de delta » :
    le premier se tait, le second doit dire pourquoi."""
    m = _metric()
    html_str = _render_kpi_html(monkeypatch, m, 6.0, prev=None)
    assert "normale non calculable" in html_str


def test_kpi_tile_rounds_a_negligible_delta_to_silence(monkeypatch):
    """Le test porte sur la chaîne AFFICHÉE : un écart de 0,04 rendu « +0,0 »
    est un zéro à l'écran, quoi qu'en dise la virgule flottante."""
    m = _metric(fmt="{:.1f}")
    html_str = _render_kpi_html(monkeypatch, m, 50.04, prev=50.0)
    assert "visibility:hidden" in html_str


def test_sparkline_bounds_are_named_not_deduced_from_position(monkeypatch):
    """Nus aux deux bouts d'une ligne, les deux nombres se lisaient comme un
    début et une fin de série — au point que sur la dépense du Bilan, « 1 622 »
    était à la fois la valeur du jour et le minimum de la fenêtre."""
    m = _metric(fmt="{:.0f}")
    # `_render_kpi_html` trace toujours la même série, 1 → 2 → 3.
    html_str = _render_kpi_html(monkeypatch, m, 3.0, prev=1.0)
    scale = html_str.split('class="bevel-kpi-scale"')[1]
    assert "<i>min</i> 1" in scale
    assert "<i>max</i> 3" in scale


# --- palette d'identité vs budget de statut ------------------------------
def test_series_palette_never_borrows_a_status_colour():
    """`categorical` valait exactement `status.good` en slot 2 et
    `status.critical` en slot 7 : la VO2max était tracée en vert-« bon » et la FC
    de repos en rouge-« alerte ». Une identité de série n'est pas un jugement."""
    for tokens in (theme.DARK, theme.LIGHT):
        status = {v.lower() for v in tokens["status"].values()}
        overlap = status & {c.lower() for c in tokens["series"]}
        assert not overlap, f"teintes de statut dans la palette de séries : {overlap}"


def test_no_series_hue_falls_back_into_the_ink_family():
    """L'autre piège du budget couleur, symétrique du premier.

    Éviter les teintes de statut ne suffit pas : une teinte trop désaturée
    rejoint la famille des encres — celle de la grille, des axes et du pointillé
    de normale — et sa courbe se lit comme du chrome. C'était le cas de l'ardoise
    (#8AA0B8, saturation 0,24) : le graphe de FC de repos paraissait désactivé à
    côté de ses voisins.
    """
    import colorsys  # noqa: PLC0415
    for tokens in (theme.DARK, theme.LIGHT):
        for hexa in tokens["series"]:
            h = hexa.lstrip("#")
            r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
            _, _, sat = colorsys.rgb_to_hls(r, g, b)
            assert sat >= 0.35, f"{hexa} (saturation {sat:.2f}) appartient aux encres"


def test_series_palette_has_the_same_length_as_categorical():
    """`palette_index` du registre indexe les deux : un jeu plus court
    recyclerait silencieusement les teintes."""
    for tokens in (theme.DARK, theme.LIGHT):
        assert len(tokens["series"]) == len(tokens["categorical"])


def test_metric_chart_tints_the_baseline_band_with_the_metric_colour():
    """En gris d'encre, la bande passait pour une ombre portée. Teintée à faible
    opacité, elle se lit comme « ma zone normale pour CETTE métrique »."""
    m = _metric(baseline="personal", palette_index=0)
    fig = charts.metric_chart(
        pd.DataFrame({"local_date": pd.date_range("2026-01-01", periods=30),
                      "test_metric": [50.0 + i % 4 for i in range(30)]}), m)
    band = next(tr for tr in fig.data if tr.fill == "toself")
    hue = theme.active_tokens()["series"][0]
    assert band.fillcolor == charts._with_opacity(hue, 0.10)


# --- anatomie commune : poids visuel et étiquette de fin de ligne --------
def _frame(n=40, pattern=lambda i: 50.0 + (i % 5)):
    return pd.DataFrame({"local_date": pd.date_range("2026-01-01", periods=n),
                         "test_metric": [pattern(i) for i in range(n)]})


def test_visual_weight_puts_the_measurement_above_its_reference():
    """L'ordre était inversé : la bande de référence était l'objet le plus lourd
    du graphe et la mesure quotidienne le plus léger. Le décor dominait la
    donnée."""
    fig = charts.metric_chart(_frame(), _metric(baseline="personal", palette_index=0))
    hue = theme.active_tokens()["series"][0]
    band = next(tr for tr in fig.data if tr.fill == "toself")
    daily = next(tr for tr in fig.data if tr.name == "Quotidien")
    smooth = next(tr for tr in fig.data if str(tr.name).startswith("Moyenne"))

    assert band.fillcolor == charts._with_opacity(hue, 0.10)
    assert daily.line.color == charts._with_opacity(hue, 0.35)
    assert smooth.line.color == hue, "la moyenne est la seule trace en teinte pleine"
    assert smooth.line.width > daily.line.width
    assert smooth.line.shape == "spline"


def test_the_smoothed_curve_carries_its_value_at_the_end():
    """Ce que la légende ne donnait pas : la valeur. Écrite au bout de la
    courbe, elle réconcilie d'un coup d'œil le graphe et sa tuile."""
    fig = charts.metric_chart(_frame(pattern=lambda i: 50.0), _metric(fmt="{:.0f}"))
    assert [a.text for a in fig.layout.annotations] == ["Moyenne 7j · 50"]
    dot = fig.data[-1]
    assert dot.mode == "markers" and dot.marker.size == 4


def test_the_dotted_baseline_never_outshines_the_measurement():
    """Un repère plus visible que la mesure qu'il situe inverse le sens du
    graphe."""
    fig = charts.metric_chart(_frame(), _metric(baseline="personal"))
    dotted = next(tr for tr in fig.data
                  if tr.line.dash == "dot" and tr.showlegend is False)
    assert dotted.line.width == 1
    assert "rgba" in dotted.line.color, "encre effacée, pas une couleur pleine"


def test_the_last_day_is_always_a_tick():
    """La dernière graduation s'arrêtait au 17 quand les données allaient au 24 :
    l'œil terminait sa lecture sur une date fausse."""
    for n in (10, 28, 37, 180):
        dates = pd.date_range("2026-01-01", periods=n)
        fig = charts.fr_date_axis(go.Figure(), dates)
        assert fig.layout.xaxis.tickvals[-1] == dates[-1], n
        assert fig.layout.xaxis.tickvals[0] == dates[0], n


def test_the_last_tick_is_the_most_contrasted():
    fig = charts.fr_date_axis(go.Figure(), pd.date_range("2026-01-01", periods=37))
    labels = list(fig.layout.xaxis.ticktext)
    assert theme.active_tokens()["ink_secondary"] in labels[-1]
    assert all("<span" not in x for x in labels[:-1])


def test_side_by_side_charts_share_the_same_plotting_geometry():
    """Deux graphes voisins dont les valeurs n'ont pas le même nombre de chiffres
    obtenaient deux largeurs utiles différentes : leurs axes X ne se
    correspondaient plus, et « l'un monte pendant que l'autre descend » devenait
    illisible."""
    left = charts.metric_chart(_frame(pattern=lambda i: 60.0 + i % 5),
                               _metric(fmt="{:.0f}"), height=240)
    right = charts.metric_chart(_frame(pattern=lambda i: 4000.0 + i % 5),
                                _metric(fmt="{:.0f}"), height=240)
    assert left.layout.margin == right.layout.margin
    assert left.layout.margin.autoexpand is False, (
        "sinon Plotly élargit la marge pour loger ses graduations"
    )


# --- axe X : plafond de graduations, jamais incliné ----------------------
@pytest.mark.parametrize("n", [3, 10, 37, 180, 400])
def test_fr_date_axis_never_exceeds_its_tick_ceiling(n):
    """`max_ticks` était une cible : le pas se calculait sur le nombre de
    graduations et non sur le nombre d'intervalles, d'où sept graduations pour
    cinq demandées."""
    fig = charts.fr_date_axis(go.Figure(), pd.date_range("2026-01-01", periods=n))
    assert len(fig.layout.xaxis.tickvals) <= 5


def test_date_labels_are_never_tilted():
    """Laissé libre, Plotly incline les étiquettes des graphes étroits et pas
    des larges : deux graphes voisins semblaient mal rendus."""
    assert charts.base_layout()["xaxis"]["tickangle"] == 0


def test_horizontal_grid_is_visible_ink_and_bounded():
    layout = charts.base_layout(y_title="u")
    assert layout["yaxis"]["showgrid"] is True
    assert layout["yaxis"]["gridcolor"] == theme.active_tokens()["grid_line"]
    # Trois graduations : la valeur exacte se lit au bout de la courbe, l'axe ne
    # donne plus que l'ordre de grandeur.
    assert layout["yaxis"]["nticks"] == 3


# --- zone d'amorçage -----------------------------------------------------
def test_metric_chart_shades_the_warmup_window():
    """Propriété d'une PORTION de courbe : elle se dessine sur la courbe, elle
    ne se raconte pas en légende sous le graphe."""
    df = pd.DataFrame({"local_date": pd.date_range("2026-01-01", periods=60),
                       "test_metric": [float(i) for i in range(60)]})
    m = _metric(baseline="none")
    plain = charts.metric_chart(df, m)
    shaded = charts.metric_chart(df, m, warmup_until=pd.Timestamp("2026-02-11"),
                                 warmup_label="amorçage")
    # DEUX formes : le fond grisé, et le filet vertical qui dit où il s'arrête.
    # À 10 % d'opacité, le seul changement de fond ne montrait pas la frontière.
    assert len(shaded.layout.shapes) == len(plain.layout.shapes) + 2
    note = next(a for a in shaded.layout.annotations if a.text == "amorçage")
    # À mi-hauteur DANS la zone : posée sur le bord supérieur, elle se lisait
    # comme le titre du graphe.
    assert (note.y, note.yref) == (0.5, "paper")


def test_warmup_shading_is_skipped_when_the_window_is_already_past():
    df = pd.DataFrame({"local_date": pd.date_range("2026-06-01", periods=30),
                       "test_metric": [float(i) for i in range(30)]})
    m = _metric(baseline="none")
    plain = charts.metric_chart(df, m)
    late = charts.metric_chart(df, m, warmup_until=pd.Timestamp("2026-01-01"))
    assert len(late.layout.shapes) == len(plain.layout.shapes)


# --- cadrage vertical et notes de contexte -------------------------------
def _hr_frame(values):
    return pd.DataFrame({
        "local_date": pd.date_range("2026-01-01", periods=len(values), freq="D"),
        "resting_hr": values,
    })


def test_metric_chart_frames_the_daily_series_and_not_just_its_moving_average():
    """La série quotidienne est la plus ample par construction ; la moyenne
    glissante et la bande de baseline la resserrent. Un cadrage calé sur ces
    dernières coupait la courbe qui porte l'information."""
    values = [65.0] * 30 + [58.9, 59.0, 58.5, 59.2, 71.0]
    fig = charts.metric_chart(_hr_frame(values), metrics.require("resting_hr"))
    lo, hi = fig.layout.yaxis.range
    assert lo < min(values), f"borne basse {lo} coupe le minimum {min(values)}"
    assert hi > max(values), f"borne haute {hi} coupe le maximum {max(values)}"


def test_fit_y_range_includes_a_reference_line_that_is_not_a_trace():
    fig = go.Figure(go.Scatter(y=[10.0, 12.0]))
    charts.fit_y_range(fig, extra=(40.0,))
    assert fig.layout.yaxis.range[1] > 40.0


def test_fit_y_range_survives_a_perfectly_flat_series():
    """Un `pad` proportionnel vaut zéro ici : sans repli, Plotly recevrait une
    plage d'épaisseur nulle."""
    fig = go.Figure(go.Scatter(y=[7.0, 7.0, 7.0]))
    charts.fit_y_range(fig)
    lo, hi = fig.layout.yaxis.range
    assert lo < 7.0 < hi


def test_metric_chart_carries_no_chrome_at_all():
    """LE test structurel : la figure ne porte plus ni titre, ni légende, ni
    note. Titre, sous-titre et légende Plotly visent tous la même bande au-dessus
    du plot — Plotly ne les empile pas et ne dimensionne aucune marge pour les
    annotations. Tant qu'ils y sont, la collision est une question de largeur de
    colonne, pas de réglage."""
    fig = charts.metric_chart(
        _hr_frame([60.0 + i * 0.1 for i in range(40)]), metrics.require("resting_hr"),
        show_trend=True, show_confidence=True,
    )
    assert fig.layout.title.text is None
    assert fig.layout.showlegend is False
    assert fig.layout.margin.t == 8, "la figure récupère toute sa boîte"
    # Pas de titre d'axe rotatif : le pire rapport lisibilité/place d'une page.
    assert fig.layout.yaxis.title.text is None
    # La SEULE annotation restante est l'étiquette de fin de courbe, qui porte
    # la valeur — ce que la légende ne donnait justement pas.
    assert [a.text for a in fig.layout.annotations] == ["Moyenne 7j · 64"]
    assert fig.layout.margin.r > 100, "la marge droite loge cette étiquette"


def test_chart_header_carries_the_chrome_instead():
    """Ce que la figure a perdu, l'en-tête HTML le porte — sinon la
    restructuration serait une suppression."""
    fig = charts.metric_chart(
        _hr_frame([60.0 + i * 0.1 for i in range(40)]), metrics.require("resting_hr"),
        show_trend=True, show_confidence=True,
    )
    head = charts.chart_header_html(dict(fig.layout.meta))
    assert "Fréquence cardiaque au repos" in head
    assert "hausse" in head
    # Aucun appareil statistique en surface : ni effectif, ni p-value.
    assert "n=" not in head and "p=" not in head
    # Et AUCUNE légende : elle est au bout des courbes, avec la valeur en prime.
    assert "bevel-chart-legend" not in head


def test_chart_header_omits_the_title_the_card_already_carries():
    fig = charts.metric_chart(
        _hr_frame([60.0 + i * 0.1 for i in range(40)]), metrics.require("resting_hr"),
        title="", show_trend=True,
    )
    head = charts.chart_header_html(dict(fig.layout.meta))
    assert "bevel-chart-title" not in head
    assert "bevel-chart-note" in head, "la note de tendance, elle, reste due"


# --- graphe vide --------------------------------------------------------
def test_empty_figure_never_raises_and_carries_message():
    fig = charts._empty_figure("Titre", 300, "Message de test")
    assert isinstance(fig, go.Figure)
    assert fig.layout.annotations[0].text == "Message de test"


# --- device_band / mark_partial_days (formes ajoutées) -----------------------
def test_device_band_shades_only_when_data_predates_device_start():
    before = pd.DataFrame({"local_date": pd.date_range("2026-06-01", periods=5)})
    fig_before = charts.device_band(go.Figure(), before, "local_date")
    assert len(fig_before.layout.shapes) == 1

    after = pd.DataFrame({"local_date": pd.date_range("2026-06-20", periods=5)})
    fig_after = charts.device_band(go.Figure(), after, "local_date")
    assert len(fig_after.layout.shapes) == 0


def test_mark_partial_days_only_shades_flagged_rows():
    df = pd.DataFrame({
        "local_date": pd.date_range("2026-01-01", periods=4),
        "is_partial_day": [True, False, False, False],
        "is_missing_day": [False, False, True, False],
    })
    fig = go.Figure()
    charts.mark_partial_days(fig, df)
    assert len(fig.layout.shapes) == 2


def test_mark_partial_days_noop_when_nothing_flagged():
    df = pd.DataFrame({"local_date": pd.date_range("2026-01-01", periods=3), "is_partial_day": [False] * 3})
    fig = go.Figure()
    charts.mark_partial_days(fig, df)
    assert len(fig.layout.shapes) == 0


def test_mark_partial_days_handles_empty_df_without_raising():
    fig = charts.mark_partial_days(go.Figure(), pd.DataFrame())
    assert isinstance(fig, go.Figure)


# --- metric_chart : moyenne glissante CALENDAIRE, pas positionnelle ---------
def test_metric_chart_rolling_mean_is_calendar_aware_not_row_aware():
    """Même bug que celui corrigé dans stats.rolling_baseline : un point isolé
    à 8 jours du précédent ne doit pas être moyenné avec lui sous prétexte
    qu'il s'agit de la "3e ligne" d'une fenêtre à 2 jours."""
    m = _metric(key="v", ma_window=2, baseline="personal")
    df = pd.DataFrame({
        "local_date": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-10"]),
        "v": [10.0, 20.0, 100.0],
    })
    fig = charts.metric_chart(df, m, show_baseline=False)
    ma_trace = next(tr for tr in fig.data if tr.name and tr.name.startswith("Moyenne"))
    assert math.isnan(ma_trace.y[0]), "1 seul point dans sa fenêtre 2j : pas assez pour une moyenne"
    assert ma_trace.y[1] == pytest.approx(15.0), "1er et 2e janvier sont à 1 jour d'écart : moyennés ensemble"
    assert math.isnan(ma_trace.y[2]), "10 janvier est isolé (8j du point précédent) : ne doit PAS absorber les 2 autres"


# --- composants sur DataFrame vide / tout-NULL : jamais d'exception ---------
@pytest.mark.parametrize("empty_df", [pd.DataFrame(), pd.DataFrame({"local_date": [], "v": []})])
def test_metric_chart_handles_empty_data_without_raising(empty_df):
    m = _metric(key="v")
    fig = charts.metric_chart(empty_df, m)
    assert isinstance(fig, go.Figure)
    assert fig.layout.annotations[0].text  # message d'état vide


def test_metric_chart_handles_missing_column_without_raising():
    m = _metric(key="colonne_absente")
    fig = charts.metric_chart(pd.DataFrame({"local_date": pd.date_range("2026-01-01", periods=3)}), m)
    assert isinstance(fig, go.Figure)


def test_metric_chart_handles_all_null_column_without_raising():
    m = _metric(key="v")
    df = pd.DataFrame({"local_date": pd.date_range("2026-01-01", periods=5), "v": [None] * 5})
    fig = charts.metric_chart(df, m)
    assert isinstance(fig, go.Figure)


def test_baseline_band_handles_empty_df_without_raising():
    fig = charts.baseline_band(go.Figure(), pd.DataFrame())
    assert isinstance(fig, go.Figure)


def test_gauge_handles_no_ranges_and_none_value_without_raising():
    assert isinstance(charts.gauge(50, []), go.Figure)
    fig = charts.gauge(None, [(-10, 10, "good")])
    assert isinstance(fig, go.Figure)


def test_distribution_handles_empty_and_none_series_without_raising():
    assert isinstance(charts.distribution(pd.Series(dtype=float)), go.Figure)
    assert isinstance(charts.distribution(None), go.Figure)


def test_calendar_heatmap_handles_empty_df_without_raising():
    fig = charts.calendar_heatmap(pd.DataFrame(), "steps")
    assert isinstance(fig, go.Figure)


def test_radar_handles_empty_dict_without_raising():
    fig = charts.radar({})
    assert isinstance(fig, go.Figure)


def test_waterfall_handles_empty_components_without_raising():
    fig = charts.waterfall([])
    assert isinstance(fig, go.Figure)


def test_intraday_hr_handles_empty_df_without_raising():
    fig = charts.intraday_hr(pd.DataFrame())
    assert isinstance(fig, go.Figure)


def test_correlation_heatmap_handles_empty_df_without_raising():
    fig = charts.correlation_heatmap(pd.DataFrame())
    assert isinstance(fig, go.Figure)


# --- correlation_heatmap : le vrai comportement attendu ---------------------
def test_correlation_heatmap_masks_non_significant_pairs():
    """Le composant doit griser (NaN dans l'overlay coloré) les paires NON
    significatives -- c'est tout le sens de son existence (cf. stats.corr_table :
    croiser beaucoup de métriques produit des r "significatifs" par hasard)."""
    corr_df = pd.DataFrame([
        {"a": "x", "b": "y", "r": 0.9, "n": 30, "p_value": 0.001, "is_significant": True},
        {"a": "x", "b": "z", "r": 0.5, "n": 30, "p_value": 0.4, "is_significant": False},
        {"a": "y", "b": "z", "r": -0.2, "n": 30, "p_value": 0.6, "is_significant": False},
    ])
    fig = charts.correlation_heatmap(corr_df)
    overlay = fig.data[1]  # 2e trace = la couche colorée par-dessus le fond gris
    cols = sorted({"x", "y", "z"})
    idx = {c: i for i, c in enumerate(cols)}
    assert overlay.z[idx["x"]][idx["y"]] == pytest.approx(0.9)
    assert math.isnan(overlay.z[idx["x"]][idx["z"]])
    assert math.isnan(overlay.z[idx["y"]][idx["z"]])


# --- la tuile KPI : ce qu'elle rend vraiment ---------------------------------
def _render_kpi_html(monkeypatch, metric, value, prev=None, **kwargs) -> str:
    """HTML produit par `kpi_card`, capturé au vol.

    La tuile est un unique bloc `st.markdown` : c'est le seul endroit où l'on
    puisse vérifier ce qui atteint réellement le navigateur — les règles de
    couleur, elles, ne se lisent pas dans la feuille de style, elles sont
    posées en inline par cette fonction.
    """
    captured: list[str] = []
    monkeypatch.setattr(charts.st, "markdown", lambda html, **kw: captured.append(html))
    charts.kpi_card(metric, value, prev, series=pd.Series([1.0, 2.0, 3.0]), **kwargs)
    return captured[0]


def test_kpi_pill_stays_grey_on_a_metric_whose_drop_is_not_a_signal(monkeypatch):
    """Une charge ou une dépense en baisse un jour de repos est un FAIT.
    La peindre en rouge invente un jugement que la donnée ne porte pas."""
    m = _metric(key="cardio_load_total", direction=1)
    html = _render_kpi_html(monkeypatch, m, 40.0, prev=61.0)
    t = theme.active_tokens()
    assert t["ink_muted"] in html.split('class="bevel-kpi-pill"')[1].split(">")[0]
    assert charts.status_hex("serious", t) not in html


def test_kpi_pill_colours_only_a_signal_metric_going_the_wrong_way(monkeypatch):
    from health import metrics as _metrics
    m = _metric(key="hrv_rmssd", direction=1)
    assert m.key in _metrics.SIGNAL_KEYS
    t = theme.active_tokens()
    adverse = _render_kpi_html(monkeypatch, m, 32.0, prev=48.0)
    assert charts.status_hex("serious", t) in adverse
    # Le même signal DANS LE BON SENS reste gris : la couleur signale un
    # retard, elle n'est pas la marque de la métrique.
    favourable = _render_kpi_html(monkeypatch, m, 55.0, prev=48.0)
    assert charts.status_hex("serious", t) not in favourable


def test_only_two_metrics_may_ever_wear_colour_in_the_grid():
    """Le budget couleur est une quantité, pas une intention : deux clés au
    maximum, sinon la grille redevient un sapin de Noël."""
    from health import metrics as _metrics
    assert len(_metrics.SIGNAL_KEYS) <= 2
    assert _metrics.SIGNAL_KEYS <= set(_metrics.METRICS)


def test_kpi_tile_carries_no_status_glyph(monkeypatch):
    """Un marqueur unique dans une grille de huit se lit comme un bug avant de
    se lire comme une information. Soit toutes les tuiles, soit aucune."""
    m = _metric(key="hrv_rmssd", direction=1)
    html = _render_kpi_html(monkeypatch, m, 10.0, prev=90.0, z=-3.0)
    assert "bevel-flag" not in html
    assert not any(g in html for g in charts.STATUS_GLYPHS.values())


def test_the_unit_appears_exactly_once_per_tile(monkeypatch):
    """Elle était sur la valeur principale ET sur la borne haute : deux fois par
    tuile, seize fois sur une grille de huit. Elle reste sur la valeur — la
    borne min/max est une annotation d'échelle, pas une grandeur à qualifier."""
    m = _metric(unit=" ml/kg/min", fmt="{:.1f}")
    html_str = _render_kpi_html(monkeypatch, m, 2.0, prev=1.0)
    assert html_str.count("ml/kg/min") == 1
    scale = html_str.split('class="bevel-kpi-scale"')[1]
    assert "ml/kg/min" not in scale


def test_no_tile_carries_a_legend_of_its_own(monkeypatch):
    """La légende du pointillé vaut pour les huit tuiles : elle vit sur la ligne
    d'intitulé de groupe, qui les couvre. Posée sous la première tuile, elle lui
    ajoutait une ligne que ses trois voisines n'avaient pas et décalait le bas
    de toute la rangée."""
    html_str = _render_kpi_html(monkeypatch, _metric(), 2.0, prev=1.0)
    assert "legend" not in html_str
    assert "moyenne 28 j" not in html_str


def test_kpi_tile_exposes_both_resting_and_hover_sparkline_colours(monkeypatch):
    """Gris au repos, couleur de la métrique au survol. Les deux jeux sont
    posés sur la TUILE ; le SVG n'en porte aucun, sinon l'inline battrait la
    règle de survol et la courbe ne se colorerait jamais."""
    t = theme.active_tokens()
    m = _metric(palette_index=3)
    html = _render_kpi_html(monkeypatch, m, 2.0, prev=1.0)
    tile_style = html.split('style="')[1].split('"')[0]
    assert f"--bevel-spark-cold:{t['ink_secondary']}" in tile_style
    # `series` et non `categorical` : la teinte de survol doit être celle que la
    # métrique porte dans les graphes, sinon la promesse « c'est sa couleur
    # ailleurs » tombe sur la tuile qu'on vient justement de survoler.
    assert f"--bevel-spark-hot:{t['series'][3]}" in tile_style
    svg = html.split("<svg")[1].split(">")[0]
    assert "--bevel-spark" not in svg, "une déclaration inline sur le SVG bat le survol"


def test_sparkline_point_and_curve_read_their_colour_from_the_cascade():
    svg = charts._sparkline_svg(pd.Series([1.0, 3.0, 2.0]), "#123456")
    assert 'stroke="var(--bevel-spark, #123456)"' in svg
    assert 'class="bevel-spark-dot"' in svg and 'stroke-width="3"' in svg


def test_effort_bar_legend_skips_zones_that_did_not_happen():
    """« Pic · 0 min » n'est pas une information, c'est une case vide. Sur une
    journée ordinaire, deux zones sur trois sont à zéro."""
    html_str = charts.effort_bar([("Modérée", 6.0), ("Soutenue", 0.0), ("Pic", 0.0)])
    legend = html_str.split('class="bevel-effort-legend"')[1]
    assert "Modérée" in legend
    assert "Soutenue" not in legend and "Pic" not in legend


def test_effort_bar_keeps_a_zone_colour_tied_to_its_intensity_not_its_rank():
    """Une zone absente ne doit pas décaler la rampe : le violet du « Pic »
    resterait le même quel que soit le nombre de zones affichées."""
    t = theme.active_tokens()
    full = charts.effort_bar([("Modérée", 5.0), ("Soutenue", 5.0), ("Pic", 5.0)])
    gapped = charts.effort_bar([("Modérée", 5.0), ("Soutenue", 0.0), ("Pic", 5.0)])

    def peak_swatch(h):
        return h.split('class="bevel-effort-legend"')[1].split("background:")[-1].split('"')[0]
    assert peak_swatch(full) == peak_swatch(gapped)
    rgb = tuple(int(t["accent"].lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    assert peak_swatch(full) == f"rgba({rgb[0]},{rgb[1]},{rgb[2]},1.0)", (
        "le sommet de la rampe est l'accent à pleine intensité"
    )


# --- l'axe d'effort ne s'étire pas -------------------------------------------
def test_effort_bar_holds_its_axis_and_flags_the_day_that_exceeds_it():
    """Étirer l'axe pour contenir un jour hors norme écraserait les quatre-vingt-
    dix jours ordinaires pour faire de la place à l'exception. Un jour
    exceptionnel doit se voir, pas diluer l'échelle de tous les autres."""
    html_str = charts.effort_bar([("Modérée", 60.0), ("Pic", 60.0)], scale_max=30.0)
    assert "bevel-effort-over" in html_str, "le dépassement doit être signalé"
    # Barre pleine, mais les proportions entre zones restent justes.
    assert _seg_widths(html_str) == [pytest.approx(50.0), pytest.approx(50.0)]


def test_effort_bar_leaves_room_when_the_day_is_below_its_axis():
    html_str = charts.effort_bar([("Modérée", 15.0)], scale_max=30.0)
    assert "bevel-effort-over" not in html_str
    assert _seg_widths(html_str) == [50.0]


# --- la réglette : quatre paliers réellement distincts -----------------------
def test_form_rail_gives_every_zone_a_visibly_different_band():
    """`critical`/`serious` partagent la famille rouge et `good`/`excellent` la
    famille verte : à opacité égale, quatre paliers ne donnaient que deux bandes
    visibles sous quatre étiquettes."""
    ranges = [(-8.0, -5.0, "critical"), (-5.0, -2.0, "serious"),
              (-2.0, 1.5, "good"), (1.5, 5.0, "excellent")]
    html_str = charts.form_rail(0.0, ranges, zone_labels={
        "critical": "Surchargé", "serious": "En charge",
        "good": "Équilibré", "excellent": "Frais"})
    zones = html_str.split('class="bevel-rail-zone"')[1:]
    assert len(zones) == 4
    backgrounds = [z.split("background:")[1].split('"')[0] for z in zones]
    assert len(set(backgrounds)) == 4, f"paliers indistinguables : {backgrounds}"


def test_form_rail_names_all_four_zones_including_the_narrowest():
    """Une zone colorée mais anonyme est pire qu'un nom serré : le lecteur la
    voit et cherche en vain à quoi elle correspond."""
    ranges = [(-8.0, -5.0, "critical"), (-5.0, -2.0, "serious"),
              (-2.0, 1.5, "good"), (1.5, 5.0, "excellent")]
    labels = {"critical": "Surchargé", "serious": "En charge",
              "good": "Équilibré", "excellent": "Frais"}
    html_str = charts.form_rail(0.0, ranges, zone_labels=labels)
    for name in labels.values():
        assert name in html_str, f"« {name} » manque à la légende de la réglette"


def test_form_rail_says_which_point_is_which():
    """Deux points sur une règle, l'un plein l'autre creux, ne disent pas
    d'eux-mêmes lequel est aujourd'hui."""
    ranges = [(-8.0, 0.0, "serious"), (0.0, 8.0, "good")]
    html_str = charts.form_rail(3.0, ranges, previous=-2.0)
    assert "bevel-rail-ghost-label" in html_str and "il y a 7 j" in html_str
    # Sans repère précédent, pas de rangée de note vide.
    assert "bevel-rail-notes" not in charts.form_rail(3.0, ranges)


def test_form_rail_clamps_a_value_that_runs_off_its_scale():
    """L'échelle est figée : une valeur hors bornes se pose au bout, elle ne
    dilate pas la règle des autres jours."""
    ranges = [(-8.0, 0.0, "serious"), (0.0, 8.0, "good")]
    left = charts.form_rail(-40.0, ranges)
    assert "left:0.00%" in left
    assert "left:100.00%" in charts.form_rail(40.0, ranges)

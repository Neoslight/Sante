"""Thème Plotly partagé et constructeurs de graphiques réutilisables.

Palette reprise telle quelle de la référence validée du skill dataviz (ordre
catégoriel fixe, rampe séquentielle bleue, couleurs de statut). Les couleurs
elles-mêmes vivent dans `theme.py` (jetons clair/sombre) : ce fichier ne code
plus aucune couleur en dur, tout passe par `theme.active_tokens()` (ou par
`muscle_group_colors()` / `status_hex()` pour les dérivés) pour que les
graphes restent lisibles quel que soit le thème Streamlit actif. Il n'y a
plus de constantes de couleurs figées sur un thème : les anciennes constantes
de module (CATEGORICAL, STATUS, INK_*, SURFACE, MUSCLE_GROUP_COLORS...)
figeaient de fait le thème clair et produisaient une palette claire sur fond
sombre — elles ont été supprimées.

Convention d'annotation UNIQUE, à respecter par tous les composants de ce
fichier (et par toute page qui en ajoute de nouveaux) :

    - bande GRISE           = baseline personnelle (health.stats.rolling_baseline)
    - ligne POINTILLÉE      = objectif (metric.target / seuil fixe)
    - bande VERTE           = zone optimale (metric.good_range)
    - opacité réduite       = donnée partielle ou non fiable (jour partiel,
                              période sans appareil, métrique en calibration)

Une couleur catégorielle ne sert JAMAIS à coder une baseline, un objectif ou
une zone optimale : ces trois usages sont sémantiques, pas décoratifs, et
doivent rester reconnaissables d'un graphe à l'autre sans lire la légende.
"""
from __future__ import annotations

import html
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import theme  # noqa: E402
from health import stats  # noqa: E402
from health import metrics  # noqa: E402
from health.metrics import Metric, _fr_number  # noqa: E402

# --- Groupes musculaires / statuts : ordre et libellés fixes (les couleurs,
# elles, dépendent du thème actif -- voir muscle_group_colors() plus bas) ----
MUSCLE_GROUP_ORDER = ["jambes", "gainage", "haut_du_corps", "cou_epaules", "cardio", "mobilite", "autre"]
MUSCLE_GROUP_LABELS = {
    "jambes": "Jambes",
    "gainage": "Gainage",
    "haut_du_corps": "Haut du corps",
    "cou_epaules": "Cou & épaules",
    "cardio": "Cardio",
    "mobilite": "Mobilité",
    "autre": "Autre",
}

STATUS_LABELS = {
    "critical": "Critique", "serious": "Faible", "warning": "Attention",
    "good": "Bon", "excellent": "Excellent", "neutral": "—",
}

# Le statut ne doit pas reposer sur la SEULE couleur : une pastille verte et
# une pastille orange sont le même gris pour un daltonien (≈ 8 % des hommes),
# et à l'impression. Chaque niveau porte donc aussi une forme distincte.
#
# Triangles PLEINS uniquement : les triangles évidés (▽ △) se réduisent à un
# accent illisible dès qu'on descend sous 13 px, là où le plein garde sa
# silhouette. Le niveau se lit alors à la taille (petit = notable, grand =
# critique) et au sens, deux canaux qui survivent au monochrome.
STATUS_GLYPHS = {
    "critical": "▼", "serious": "▾", "warning": "◆", "good": "●",
    "excellent": "▴", "neutral": "·",
}

DEVICE_START = "2026-06-17"


def muscle_group_colors() -> dict[str, str]:
    """Couleur catégorielle par groupe musculaire, adaptée au thème actif.

    Remplace l'ancienne constante `MUSCLE_GROUP_COLORS`, figée sur
    `theme.LIGHT["categorical"]` : consommée en dur par `muscle_group_bar`,
    elle rendait une palette claire sur fond sombre. Un même groupe garde
    toujours le même INDEX de couleur d'un graphe à l'autre (muscle_group_bar,
    radar) ; seule la teinte réelle derrière cet index suit le thème."""
    t = theme.active_tokens()
    return dict(zip(MUSCLE_GROUP_ORDER, t["categorical"]))


# =============================================================================
# Utilitaires internes
# =============================================================================
def _with_opacity(hex_color: str, alpha: float) -> str:
    """Convertit un hex en rgba() -- pour les remplissages (bande de baseline,
    aire sous sparkline) sans dépendre du support d'opacité par trace."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def tint(hex_color: str, alpha: float = 0.15) -> str:
    """Version publique de `_with_opacity`, pour les fonds de pastille rendus
    en HTML par les pages (badge de forme, pastille de variation) : elles ont
    besoin de la même teinte translucide que les remplissages Plotly, et ne
    doivent pas la recalculer chacune de leur côté."""
    return _with_opacity(hex_color, alpha)


def _ramp_to_colorscale(hexes: list[str]) -> list[list]:
    """Rampe (liste de hex, ordre proche-surface -> loin) -> colorscale Plotly
    ([fraction, hex] régulièrement espacés)."""
    n = max(1, len(hexes) - 1)
    return [[i / n, c] for i, c in enumerate(hexes)]


def _empty_figure(title: str | None = None, height: int = 320,
                   message: str = "Pas de données sur cette période.") -> go.Figure:
    """Graphe vide propre : aucun composant de ce fichier ne doit lever sur un
    DataFrame vide ou tout-NULL (historique court, séries trouées)."""
    t = theme.active_tokens()
    fig = go.Figure()
    fig.update_layout(**base_layout(title, None, height))
    fig.update_xaxes(visible=False, showgrid=False)
    fig.update_yaxes(visible=False, showgrid=False)
    fig.add_annotation(
        text=message, showarrow=False, xref="paper", yref="paper", x=0.5, y=0.5,
        font=dict(color=t["ink_muted"], size=13),
    )
    return fig


def status_hex(status_key: str, t: dict | None = None) -> str:
    t = t or theme.active_tokens()
    if status_key == "excellent":
        return t["status"]["good"]
    if status_key == "neutral":
        return t["ink_muted"]
    return t["status"].get(status_key, t["ink_muted"])


_status_hex = status_hex  # alias rétro-compatible (ancien nom privé)


def sequential_scale() -> list[str]:
    """Rampe séquentielle nommée (bleu), adaptée au thème actif -- ordre
    proche-surface -> loin. À utiliser partout où une magnitude continue doit
    être encodée en couleur (calendar_heatmap, etc.) plutôt que d'écrire une
    échelle de couleurs en dur."""
    return list(theme.active_tokens()["sequential"])


def sequential_colorscale() -> list[list]:
    """Comme `sequential_scale()`, au format colorscale Plotly ([frac, hex])."""
    return _ramp_to_colorscale(sequential_scale())


def diverging_colorscale() -> list[list]:
    """Échelle divergente nommée bleu <-> gris <-> rouge (pôle bas = rouge/
    négatif, pôle haut = bleu/positif), adaptée au thème actif. Remplace toute
    échelle divergente écrite en dur (ex. la matrice de corrélation de
    l'Explorateur)."""
    t = theme.active_tokens()
    return [[0, t["diverging_low"]], [0.5, t["diverging_mid"]], [1, t["diverging_high"]]]


# =============================================================================
# Mise en page de base
# =============================================================================
def base_layout(title: str | None = None, y_title: str | None = None, height: int = 320) -> dict:
    """Mise en page Bevel : fond transparent (le fond vient de la carte
    Streamlit qui contient le graphe, pas du graphe lui-même), marges
    resserrées, axe X sans filet de fermeture. N'ajoute JAMAIS de `shape` --
    `device_band`/`mark_partial_days` sont comptés via `len(fig.layout.shapes)`
    dans les tests, un shape ajouté ici fausserait ce compte."""
    t = theme.active_tokens()
    layout = dict(
        height=height,
        margin=dict(l=8, r=8, t=32 if title else 8, b=8),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter Tight, system-ui, -apple-system, Segoe UI, sans-serif",
                   color=t["ink_secondary"], size=12),
        # `tickangle=0` explicite : laissé libre, Plotly incline les étiquettes
        # dès que la place manque — ce qui arrivait sur les graphes en demi-
        # largeur et pas sur les pleines largeurs. Deux graphes voisins avec des
        # dates inclinées d'un côté et droites de l'autre se lisent comme un
        # défaut de rendu. Le nombre de graduations s'ajuste, pas leur angle.
        xaxis=dict(showgrid=False, showline=False, tickangle=0,
                    tickfont=dict(color=t["ink_muted"])),
        yaxis=dict(
            title=y_title,
            # `grid_line` (encre à 8 %) et non `grid` (couleur pleine, invisible
            # sur la surface des cartes), et `nticks` borné : quatre ou cinq
            # lignes suffisent à lire une valeur intermédiaire, au-delà elles
            # deviennent une trame.
            showgrid=True, gridcolor=t["grid_line"], gridwidth=1, nticks=5,
            zeroline=False, showline=False, tickfont=dict(color=t["ink_muted"]),
        ),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0,
                     bgcolor="rgba(0,0,0,0)", itemsizing="constant", font=dict(color=t["ink_secondary"])),
        hovermode="x unified",
    )
    # Clé `title` OMISE, et non posée à None : `update_layout(title=None)`
    # instancie quand même l'objet Title, sérialisé en `"title": {}`. Plotly.js
    # y lit alors un `text` indéfini et écrit littéralement « undefined »
    # au-dessus du graphe, par-dessus la légende.
    if title:
        layout["title"] = dict(text=title, font=dict(size=14, color=t["ink_primary"]))
    return layout


def fit_y_range(fig: go.Figure, extra: tuple[float, ...] = (), pad: float = 0.06) -> go.Figure:
    """Cadre l'axe Y sur TOUTES les traces du graphe, plus `extra`.

    À appeler quand un graphe superpose des séries d'amplitudes très
    différentes — une série quotidienne, sa moyenne glissante et une bande de
    baseline. L'autorange de Plotly ne tient pas compte des `shape` (zone verte
    `good_range`, bandes d'appareil), et le résultat se calait sur les séries
    lissées : la série quotidienne, la plus ample par construction, se faisait
    couper en haut ou en bas du cadre.

    `extra` sert aux repères qui ne sont pas des traces (un `add_hline`
    d'objectif) : sans lui, la ligne d'objectif peut tomber hors du cadre et
    devenir invisible.
    """
    values: list[float] = [float(v) for v in extra if v is not None and np.isfinite(v)]
    for trace in fig.data:
        y = getattr(trace, "y", None)
        if y is None:
            continue
        arr = pd.to_numeric(pd.Series(list(y)), errors="coerce").dropna()
        if not arr.empty:
            values.extend((float(arr.min()), float(arr.max())))
    if not values:
        return fig
    lo, hi = min(values), max(values)
    # Série parfaitement plate : un `pad` proportionnel vaudrait zéro et Plotly
    # afficherait une bande d'épaisseur nulle. On retombe sur la valeur elle-même.
    margin = (hi - lo) * pad or (abs(hi) * pad or 1.0)
    fig.update_yaxes(range=[lo - margin, hi + margin])
    return fig


# Mois abrégés à la française, pour les axes de dates. `%b` de Plotly rend
# « Jun » / « Jul » : le formateur est côté navigateur et suit sa locale, pas
# la nôtre. Les étiquettes sont donc calculées ici, en Python.
_MONTHS_ABBR_FR = ["janv.", "févr.", "mars", "avr.", "mai", "juin",
                   "juil.", "août", "sept.", "oct.", "nov.", "déc."]


def fr_date_axis(fig: go.Figure, dates, max_ticks: int = 5) -> go.Figure:
    """Étiquettes d'axe X en français (« 29 juin », « 2 juil. »).

    L'année n'est écrite qu'une fois, sur le premier tick : la répéter à chaque
    graduation triple la largeur de l'étiquette pour une information qui ne
    change pas d'un bout à l'autre d'une fenêtre de quatre semaines.
    """
    d = pd.to_datetime(pd.Series(list(dates))).dropna().sort_values()
    if d.empty:
        return fig
    # `max_ticks` est un PLAFOND, pas une cible. Le pas se calculait en divisant
    # par le nombre de graduations voulu, ce qui en produisait toujours une ou
    # deux de plus une fois la dernière date ajoutée de force : 7 graduations
    # pour 5 demandées sur 37 points. En divisant les INTERVALLES par le nombre
    # d'intervalles voulu, la première et la dernière date tombent d'elles-mêmes
    # sur une graduation et le compte est exact.
    if len(d) <= max_ticks:
        ticks = list(d)
    else:
        step = -(-(len(d) - 1) // (max_ticks - 1))  # division entière par excès
        ticks = list(d.iloc[::step])
        if ticks[-1] != d.iloc[-1]:
            ticks.append(d.iloc[-1])
    labels = [f"{ts.day} {_MONTHS_ABBR_FR[ts.month - 1]}" for ts in ticks]
    labels[0] = f"{labels[0]} {ticks[0].year}"
    fig.update_xaxes(tickmode="array", tickvals=ticks, ticktext=labels)
    return fig


def device_band(fig: go.Figure, df: pd.DataFrame, date_col: str) -> go.Figure:
    """Bande grisée pour la période où le Fitbit Air n'était pas encore porté."""
    if df is None or df.empty or date_col not in df.columns:
        return fig
    t = theme.active_tokens()
    min_date = pd.to_datetime(df[date_col]).min()
    if pd.isna(min_date):
        return fig
    device_start = pd.Timestamp(DEVICE_START)
    if min_date < device_start:
        fig.add_vrect(x0=min_date, x1=device_start, fillcolor=t["ink_muted"], opacity=0.08, line_width=0)
    return fig


def mark_partial_days(fig: go.Figure, df: pd.DataFrame, date_col: str = "local_date") -> go.Figure:
    """Signale les jours `is_partial_day` / `is_missing_day` de mart.daily par
    une bande à opacité réduite -- convention "donnée partielle ou non fiable"
    documentée en tête de ce fichier. Ces jours sont déjà exclus des moyennes
    en amont (health/enrich.py) ; ce composant rend visible POURQUOI un point
    semble manquant ou aberrant sur le graphe, plutôt que de laisser un trou
    muet."""
    if df is None or df.empty or date_col not in df.columns:
        return fig
    flag_cols = [c for c in ("is_partial_day", "is_missing_day") if c in df.columns]
    if not flag_cols:
        return fig
    d = df[[date_col, *flag_cols]].copy()
    d[date_col] = pd.to_datetime(d[date_col])
    flags = pd.Series(False, index=d.index)
    for c in flag_cols:
        flags = flags | d[c].fillna(False).astype(bool)
    if not flags.any():
        return fig
    t = theme.active_tokens()
    half_day = pd.Timedelta(hours=12)
    for day in d.loc[flags, date_col]:
        fig.add_vrect(x0=day - half_day, x1=day + half_day, fillcolor=t["ink_muted"],
                      opacity=0.10, line_width=0, layer="below")
    return fig


def status_color(value: float | None, thresholds: tuple[float, float, float], higher_is_better: bool = True) -> str:
    """thresholds = (critical_bound, serious_bound, warning_bound) croissants.
    Couleur de statut adaptée au thème actif -- pour les métriques à plage
    fixe (`good_range`) sans baseline glissante exploitable, en complément de
    `stats.status_from_z` (qui suppose une normale personnelle)."""
    t = theme.active_tokens()
    if value is None or pd.isna(value):
        return t["ink_muted"]
    a, b, c = thresholds
    if not higher_is_better:
        value = -value
        a, b, c = -a, -b, -c
    if value < a:
        return t["status"]["critical"]
    if value < b:
        return t["status"]["serious"]
    if value < c:
        return t["status"]["warning"]
    return t["status"]["good"]


def _status_key_for_metric(metric: Metric, value: float | None, z: float | None) -> str:
    """Statut d'une métrique : z-score personnel si disponible (`direction` +
    `stats.status_from_z`), sinon comparaison directe à `good_range` via
    `status_color` pour les métriques à plage fixe (un readiness Fitbit ou une
    SpO2 se lisent contre un seuil absolu, pas contre une normale
    individuelle)."""
    if z is not None and not (isinstance(z, float) and math.isnan(z)):
        return stats.status_from_z(z, metric.direction)
    if metric.good_range is not None and value is not None and not pd.isna(value):
        lo, hi = metric.good_range
        span = (hi - lo) or 1.0
        margin = span * 0.3
        if metric.direction >= 0:
            color = status_color(value, (lo - margin, lo - margin / 2, lo), higher_is_better=True)
        else:
            color = status_color(value, (hi + margin, hi + margin / 2, hi), higher_is_better=False)
        t = theme.active_tokens()
        for key, hexval in t["status"].items():
            if hexval == color:
                return key
        return "neutral"
    return "neutral"


# =============================================================================
# Composants existants (conservés, adaptés au thème)
# =============================================================================
def line_with_trend(
    df: pd.DataFrame, x: str, y: str, title: str = "", y_title: str = "",
    ma_window: int = 7, color: str | None = None, height: int = 320, unit: str = "",
) -> go.Figure:
    """Série brute (fine) + moyenne glissante (épaisse) — convention utilisée
    partout dans ce dashboard pour lire une tendance sans bruit quotidien.

    Fenêtre positionnelle (nombre de LIGNES, pas de jours) : conservé ainsi
    pour rester correct sur les appels existants qui resamplent déjà en
    hebdomadaire avant d'appeler cette fonction (`ma_window` y compte alors des
    semaines, pas des jours). Pour une fenêtre calendaire correcte sur des
    données quotidiennes trouées, voir `metric_chart`."""
    t = theme.active_tokens()
    color = color or t["categorical"][0]
    if df is None or df.empty or y not in df.columns or df[y].dropna().empty:
        return _empty_figure(title, height)

    d = df.dropna(subset=[y]).sort_values(x)
    fig = go.Figure()
    raw_text = [f"{v:.1f}{unit}" for v in d[y]]
    fig.add_trace(go.Scatter(
        x=d[x], y=d[y], mode="lines", name="Quotidien",
        line=dict(color=color, width=1), opacity=0.35,
        text=raw_text, hovertemplate="%{text}<extra>Quotidien</extra>",
    ))
    ma = d[y].rolling(ma_window, min_periods=max(2, ma_window // 3)).mean()
    ma_text = [f"{v:.1f}{unit}" if pd.notna(v) else "—" for v in ma]
    fig.add_trace(go.Scatter(
        x=d[x], y=ma, mode="lines", name=f"Moyenne {ma_window}j",
        line=dict(color=color, width=3),
        text=ma_text, hovertemplate="%{text}<extra>Moyenne " + f"{ma_window}j" + "</extra>",
    ))
    fig.update_layout(**base_layout(title, y_title, height))
    return fig


def muscle_group_bar(df: pd.DataFrame, x: str, suffix: str = "_min", y_title: str = "minutes",
                      title: str = "", height: int = 340) -> go.Figure:
    """Barres empilées par groupe musculaire (ordre catégoriel fixe).
    Attend des colonnes `<groupe><suffix>` (ex: jambes_min, gainage_min)."""
    if df is None or df.empty:
        return _empty_figure(title, height, "Aucune séance de renforcement sur cette période.")
    colors = muscle_group_colors()
    fig = go.Figure()
    for group in MUSCLE_GROUP_ORDER:
        col = f"{group}{suffix}"
        if col not in df.columns:
            continue
        text = [f"{MUSCLE_GROUP_LABELS[group]} : {v:.0f}" for v in df[col]]
        fig.add_trace(go.Bar(
            x=df[x], y=df[col], name=MUSCLE_GROUP_LABELS[group],
            marker_color=colors[group], marker_line_width=0,
            text=text, hovertemplate="%{text}<extra></extra>",
        ))
    layout = base_layout(title, y_title, height)
    layout["barmode"] = "stack"
    layout["bargap"] = 0.25
    fig.update_layout(**layout)
    return fig


def grouped_bars(categories: list[str], series: list[tuple[str, list[float]]],
                 y_title: str = "", title: str = "", height: int = 320,
                 unit: str = "") -> go.Figure:
    """Barres GROUPÉES : les mêmes catégories comparées entre deux ou trois
    séries (une semaine contre la précédente, par exemple).

    Complète `muscle_group_bar`, qui empile une composition dans le temps ;
    ici, la question est « lesquelles ont bougé, et de combien ? », et un
    empilement ne permet pas de la lire.

    La première série est la RÉFÉRENCE et se peint en encre discrète, les
    suivantes prennent la palette catégorielle : sans cette hiérarchie, deux
    séries de couleur égale laissent chercher laquelle est le passé.

    Existe parce que la page « Progression » montait ce graphe à la main —
    `import plotly.graph_objects` au milieu d'un `else`, couleurs lues dans
    `theme.active_tokens()` depuis la page. Aucune page ne doit avoir à
    connaître Plotly ni les jetons de thème pour poser une barre.
    """
    if not categories or not series:
        return _empty_figure(title, height, "Pas de quoi comparer sur cette période.")
    t = theme.active_tokens()
    fig = go.Figure()
    for rank, (name, values) in enumerate(series):
        color = t["ink_muted"] if rank == 0 else t["categorical"][(rank - 1) % len(t["categorical"])]
        fig.add_trace(go.Bar(
            name=name, x=categories, y=values,
            marker_color=color, marker_line_width=0,
            text=[f"{v:.0f}{unit}" for v in values],
            hovertemplate="%{text}<extra>" + name + "</extra>",
        ))
    layout = base_layout(title, y_title, height)
    layout["barmode"] = "group"
    layout["bargap"] = 0.25
    fig.update_layout(**layout)
    return fig


# =============================================================================
# Phase 4 — nouveaux composants
# =============================================================================
def baseline_band(fig: go.Figure, baseline_df: pd.DataFrame, date_col: str = "local_date",
                   label: str = "Baseline personnelle", color: str | None = None) -> go.Figure:
    """Bande médiane ± 1 sigma issue de `health.stats.rolling_baseline`.

    C'EST LE COMPOSANT LE PLUS IMPORTANT du dashboard : il transforme une
    série brute en information SITUÉE. Sans lui, « HRV 45 ms » ne veut rien
    dire ; avec la bande, on voit d'un coup d'œil si 45 est dans la normale de
    la personne ou un écart notable.

    `color` — la teinte d'identité de la métrique, à 8 % : la bande se lit alors
    comme « MA zone normale pour cette métrique ». En gris d'encre (l'ancien
    défaut), elle passait pour une ombre portée ou un artefact de rendu sur fond
    sombre, c'est-à-dire pour un accident et non pour une information. La règle
    « pas de couleur catégorielle » visait à empêcher qu'on la confonde avec une
    série ; c'est l'opacité qui l'en distingue, pas l'absence de teinte.
    """
    if baseline_df is None or baseline_df.empty:
        return fig
    d = baseline_df.dropna(subset=["upper", "lower", "baseline"])
    if d.empty:
        return fig
    t = theme.active_tokens()
    band_color = _with_opacity(color or t["ink_muted"], 0.08 if color else 0.14)
    fig.add_trace(go.Scatter(
        x=pd.concat([d[date_col], d[date_col][::-1]]),
        y=pd.concat([d["upper"], d["lower"][::-1]]),
        fill="toself", fillcolor=band_color, line=dict(width=0),
        hoverinfo="skip", showlegend=True, name=label,
    ))
    fig.add_trace(go.Scatter(
        x=d[date_col], y=d["baseline"], mode="lines",
        line=dict(width=1, color=t["ink_muted"], dash="dot"),
        hoverinfo="skip", showlegend=False,
    ))
    return fig


def metric_chart(
    df: pd.DataFrame, metric: Metric, x: str = "local_date", *,
    height: int = 320, show_baseline: bool | None = None, show_trend: bool = False,
    show_confidence: bool = False, title: str | None = None,
    warmup_until=None, warmup_label: str = "amorçage",
) -> go.Figure:
    """LE composant central du dashboard : à partir d'un `Metric` du registre
    (health/metrics.py) et d'un DataFrame contenant sa colonne, déduit titre,
    unité, couleur (palette_index), fenêtre de lissage et format du survol —
    et empile tout le contexte qui transforme une série brute en information
    exploitable :

      1. bande verte `good_range` (zone optimale), si définie ;
      2. bande de baseline personnelle (`baseline_band`) TEINTÉE de la métrique
         à 8 %, seulement pour les métriques `baseline="personal"` (calculée en
         CALENDAIRE via `stats.rolling_baseline`, pas positionnelle : correction
         explicite du plan) ;
      3. série quotidienne fine + moyenne glissante CALENDAIRE épaisse ;
      4. ligne pointillée d'objectif (`metric.target`), si définie ;
      5. zone d'amorçage grisée (`warmup_until`), pour les séries dont le début
         de courbe n'est pas encore la métrique mais son démarrage.

    La teinte vient de `theme.active_tokens()["series"]` et non de
    `["categorical"]` : cette dernière empiète sur le budget de statut (son
    slot 2 vaut exactement `status.good`, son slot 7 `status.critical` en
    clair). Une identité de série ne doit jamais se lire comme un jugement.

    Se comporte proprement sur un DataFrame vide, tout-NULL, ou sans la
    colonne attendue : renvoie un graphe vide avec message plutôt que de lever.
    """
    title = metric.label if title is None else title
    y_title = metric.unit.strip() or metric.short
    t = theme.active_tokens()
    color = t["series"][metric.palette_index % len(t["series"])]

    if df is None or df.empty or metric.key not in df.columns or df[metric.key].dropna().empty:
        return _empty_figure(title, height, "Pas de données pour cette métrique sur cette période.")

    d = df[[x, metric.key]].dropna(subset=[x]).copy()
    d[x] = pd.to_datetime(d[x])
    d = d.sort_values(x)
    valid = d.dropna(subset=[metric.key])
    if valid.empty:
        return _empty_figure(title, height, "Pas de données pour cette métrique sur cette période.")

    fig = go.Figure()

    if metric.good_range is not None:
        lo, hi = metric.good_range
        fig.add_hrect(y0=lo, y1=hi, fillcolor=t["status"]["good"], opacity=0.07, line_width=0, layer="below")

    use_baseline = (metric.baseline == "personal") if show_baseline is None else show_baseline
    if use_baseline and len(valid) >= 5:
        base_df = stats.rolling_baseline(valid, metric.key, date_col=x)
        baseline_band(fig, base_df, date_col=x, label="Zone normale (28j)", color=color)

    # Zone d'amorçage : une PROPRIÉTÉ d'une portion de courbe, donc dessinée sur
    # la courbe. Sur le fond de forme, les premiers jours ne mesurent pas encore
    # la capacité construite — la moyenne exponentielle part de zéro et monte
    # mécaniquement. Cette réserve vivait en légende de texte sous le graphe, où
    # elle demandait au lecteur de reporter lui-même « les 42 premiers jours »
    # sur l'axe.
    if warmup_until is not None:
        w_end = pd.Timestamp(warmup_until)
        if w_end > valid[x].min():
            fig.add_vrect(
                x0=valid[x].min(), x1=min(w_end, valid[x].max()),
                fillcolor=t["ink_muted"], opacity=0.10, line_width=0, layer="below",
                annotation_text=warmup_label, annotation_position="top left",
                annotation_font=dict(size=11, color=t["ink_muted"]),
            )

    raw_hover = [metric.format(v) for v in valid[metric.key]]
    fig.add_trace(go.Scatter(
        x=valid[x], y=valid[metric.key], mode="lines", name="Quotidien",
        line=dict(color=color, width=1), opacity=0.35,
        text=raw_hover, hovertemplate="%{text}<extra>Quotidien</extra>",
    ))

    ma_window = metric.ma_window
    ma = valid.set_index(x)[metric.key].rolling(f"{ma_window}D", min_periods=max(2, ma_window // 3)).mean()
    ma_hover = [metric.format(v) for v in ma]
    fig.add_trace(go.Scatter(
        x=ma.index, y=ma.to_numpy(), mode="lines", name=f"Moyenne {ma_window}j",
        line=dict(color=color, width=3),
        text=ma_hover, hovertemplate="%{text}<extra>Moyenne " + f"{ma_window}j" + "</extra>",
    ))

    if metric.target is not None:
        fig.add_hline(
            y=metric.target, line_dash="dot", line_color=t["ink_muted"],
            annotation_text=f"Objectif {metric.format(metric.target)}",
            annotation_font_color=t["ink_muted"],
        )

    # Figure NUE : ni titre, ni légende, ni note. Ces trois lignes sont rendues
    # en HTML au-dessus par `metric_block` (cf. `chart_header_html`), et la
    # figure récupère toute sa boîte — marge haute de 8 px et rien d'autre.
    layout = base_layout(None, y_title, height)
    layout["showlegend"] = False
    fig.update_layout(**layout)
    fr_date_axis(fig, valid[x])
    device_band(fig, valid, x)
    mark_partial_days(fig, df, x)

    # Plage Y explicite, sur l'UNION de toutes les traces.
    #
    # L'autorange de Plotly ne voit pas ce qui est posé en `shape` (bande verte
    # `good_range`, bandes d'appareil, marqueurs de jours partiels), et le
    # cadrage se calait de fait sur la moyenne glissante et la bande de
    # baseline — les deux séries les plus resserrées. La série quotidienne, qui
    # est la plus ample par construction, sortait alors du cadre : sur la FC de
    # repos, l'axe démarrait à 60 quand la série descendait à 58,9.
    fit_y_range(fig, extra=(metric.target,) if metric.target is not None else ())

    # Le chrome voyage AVEC la figure, dans `layout.meta`, plutôt que d'être
    # recalculé par l'appelant : `metric_chart` est seul à savoir quelles traces
    # il a posées (la bande de baseline est conditionnelle, la fenêtre de lissage
    # vient du registre). Une légende reconstituée à côté finirait par décrire un
    # graphe qui n'est plus celui-là.
    note = ""
    if show_trend:
        note = chart_note_text(stats.trend(valid, metric.key, date_col=x),
                                len(valid) if show_confidence else None)
    elif show_confidence:
        note = stats.confidence_note(len(valid))

    keys: list[tuple[str, str, str]] = []
    if use_baseline and len(valid) >= 5:
        keys.append(("Zone normale (28j)", "band", _with_opacity(color, 0.08)))
    keys.append(("Quotidien", "thin", color))
    keys.append((f"Moyenne {ma_window}j", "thick", color))

    fig.update_layout(meta=dict(title=title or "", note=note, keys=keys))
    return fig


def _sparkline_svg(series: pd.Series | None, color: str, width: int = 100, height: int = 34,
                   baseline: float | None = None, baseline_text: str = "",
                   band: tuple[float, float] | None = None) -> str:
    """Sparkline SVG inline (aucun Plotly) : `<polyline>` pour la courbe,
    `<path>` fermé pour le remplissage à faible opacité sous la courbe, une
    bande « fourchette habituelle » si `band` est fourni, un point plein sur le
    dernier échantillon, et -- si `baseline` est fourni -- une ligne pointillée
    horizontale à ce niveau.

    `band` = (bas, haut) de la fourchette personnelle (± 1 sigma robuste, cf.
    `stats.rolling_baseline`) : sans elle, l'échelle automatique fait paraître
    agitée une métrique parfaitement stable, puisque la courbe remplit toujours
    toute la hauteur quelle que soit l'amplitude réelle. La bande donne
    l'amplitude de référence à laquelle comparer les oscillations.

    Le point terminal marque le jour affiché : sans lui, rien ne dit lequel des
    points de la courbe est celui dont la tuile donne la valeur.

    Sans repère, une sparkline ne dit que « ça monte » ou « ça descend » ; avec
    la baseline, elle répond à la vraie question (« suis-je au-dessus ou en
    dessous de ma normale ? ») sans axe ni graduation.

    La baseline entre dans la normalisation min/max : si elle sortait du
    cadre, la ligne serait invisible ou, pire, plaquée sur un bord en laissant
    croire que la courbe la frôle. Inclure la valeur comprime un peu la courbe,
    mais ne ment pas sur la position relative des deux.

    La courbe, son aire et son point terminal sont peints en `var(--bevel-spark*)`
    et non en couleur littérale : la tuile qui les entoure porte les deux jeux de
    teintes (repos et survol) et la feuille de style bascule de l'un à l'autre.
    Les couleurs passées ici restent la valeur de repli des `var()`, pour que la
    fonction rende quelque chose de correct hors d'une tuile.

    `preserveAspectRatio="none"` étire le viewBox : l'épaisseur des traits est
    donc donnée en unités de viewBox et non en pixels écran, d'où les
    `vector-effect="non-scaling-stroke"` qui figent leur rendu à l'épaisseur
    demandée quelle que soit la largeur de la tuile.

    Cas dégénérés traités explicitement plutôt que de laisser une exception
    remonter dans une tuile KPI : série absente/vide ou à un seul point (rien
    à tracer, chaîne vide) et série plate (min == max, division par zéro dans
    la normalisation -- ligne médiane à la place).
    """
    if series is None:
        return ""
    s = pd.Series(series).dropna()
    if len(s) < 2:
        return ""
    values = s.to_numpy(dtype=float)
    n = len(values)
    has_baseline = baseline is not None and not (isinstance(baseline, float) and math.isnan(baseline))
    lo, hi = float(values.min()), float(values.max())
    if has_baseline:
        lo, hi = min(lo, float(baseline)), max(hi, float(baseline))

    # Marge haute et basse : sans elle, le point extrême de la courbe (ou la
    # baseline si elle est extrême) est tracé pile sur le bord et se fait
    # rogner d'une demi-épaisseur de trait.
    pad = 2.5
    span = height - 2 * pad

    def _y(v: float) -> float:
        if hi == lo:
            return height / 2.0
        return pad + (hi - v) / (hi - lo) * span

    xs = [i * width / (n - 1) for i in range(n)]
    ys = [_y(v) for v in values]
    line_points = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
    fill_path = (
        f"M{xs[0]:.1f},{height:.1f} "
        + " ".join(f"L{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
        + f" L{xs[-1]:.1f},{height:.1f} Z"
    )
    fill_color = _with_opacity(color, 0.12)

    t = theme.active_tokens()

    # Bande de fourchette habituelle, posée SOUS la courbe et bornée au cadre :
    # une fourchette plus large que les données déborderait sinon du viewBox et
    # peindrait toute la tuile.
    band_svg = ""
    if band is not None:
        b_lo, b_hi = float(min(band)), float(max(band))
        if not (math.isnan(b_lo) or math.isnan(b_hi)):
            y_hi = min(max(_y(b_hi), 0.0), height)
            y_lo = min(max(_y(b_lo), 0.0), height)
            if y_lo - y_hi > 0.5:
                band_svg = (
                    f'<rect x="0" y="{y_hi:.1f}" width="{width}" height="{y_lo - y_hi:.1f}" '
                    f'fill="{_with_opacity(t["ink_muted"], 0.10)}"></rect>'
                )

    baseline_svg = ""
    if has_baseline:
        yb = _y(float(baseline))
        baseline_svg = (
            f'<line x1="0" y1="{yb:.1f}" x2="{width}" y2="{yb:.1f}" '
            f'stroke="{t["ink_muted"]}" stroke-width="1" stroke-dasharray="3 3" '
            f'vector-effect="non-scaling-stroke"></line>'
        )
    # Point terminal en segment de longueur nulle à bouts ronds plutôt qu'en
    # `<circle>` : `preserveAspectRatio="none"` étire l'axe X, ce qui
    # transformerait un cercle en ellipse aplatie. Le trait, lui, garde son
    # épaisseur écran grâce à `vector-effect`, et son diamètre écran est donc
    # exactement `stroke-width`.
    #
    # En encre PRIMAIRE et non dans la teinte de la courbe : un point de la
    # même couleur qu'un trait de 1,5 px se confond avec lui, et c'est
    # justement ce point qui répond à « où suis-je dans cette courbe ? ».
    last_svg = (
        f'<line class="bevel-spark-dot" '
        f'x1="{xs[-1]:.1f}" y1="{ys[-1]:.1f}" x2="{xs[-1]:.1f}" y2="{ys[-1]:.1f}" '
        f'stroke="var(--bevel-spark-dot, {color})" stroke-width="3" stroke-linecap="round" '
        f'vector-effect="non-scaling-stroke"></line>'
    )
    title_svg = f"<title>{html.escape(baseline_text)}</title>" if baseline_text else ""
    return (
        f'<svg class="bevel-kpi-spark" viewBox="0 0 {width} {height}" '
        f'preserveAspectRatio="none" role="img">'
        f"{title_svg}"
        f"{band_svg}"
        f'<path class="bevel-spark-fill" d="{fill_path}" '
        f'fill="var(--bevel-spark-fill, {fill_color})" stroke="none"></path>'
        f"{baseline_svg}"
        f'<polyline class="bevel-spark-line" points="{line_points}" fill="none" '
        f'stroke="var(--bevel-spark, {color})" '
        f'stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round" '
        f'vector-effect="non-scaling-stroke"></polyline>'
        f"{last_svg}"
        f"</svg>"
    )


#: Statuts qui méritent un marqueur sur une tuile. Le silence est l'état par
#: défaut : `good` (dans la normale) et `neutral` (pas de quoi juger) ne disent
#: rien qu'on ne sache déjà, et une page où tout est marqué ne hiérarchise plus
#: rien.
#:
#: `excellent` en est exclu à dessein, alors qu'il l'est bien dans les nuances
#: du verdict : sur une métrique qui progresse lentement mais sûrement (VO2max,
#: FC de repos qui descend), le z-score reste au-dessus de 1 pendant des
#: SEMAINES. Un marqueur vert permanent n'attire plus l'œil sur rien — il le
#: détourne juste du seul qui compte. Une valeur en pleine forme reste lisible
#: sur la sparkline, au-dessus de sa fourchette habituelle.
ATTENTION_STATUSES = ("critical", "serious")


def micro_sparkline(series: pd.Series | None, color: str,
                    width: int = 60, height: int = 16) -> str:
    """Courbe nue, sans repère ni point terminal, pour tenir en fin de ligne.

    Version réduite de la sparkline des tuiles : ni baseline, ni fourchette, ni
    marqueur — à cette taille, ils ne seraient que du bruit. Elle ne répond qu'à
    « ça monte ou ça descend, et à quel point », ce qui est exactement ce qu'un
    constat de niveau a besoin de montrer sans quitter sa ligne.
    """
    return _sparkline_svg(series, color, width=width, height=height)


def kpi_card(
    metric: Metric, value: float | None, prev: float | None = None,
    series: pd.Series | None = None, z: float | None = None,
    *, key: str | None = None, delta_label: str = "vs moyenne",
    baseline: float | None = None, band: tuple[float, float] | None = None,
) -> None:
    """Tuile KPI complète, en trois étages : nom (+ « i ») en haut, valeur en
    gros au milieu, pastille de variation et sparkline en bas -- un unique bloc
    HTML (`.bevel-kpi` et classes filles, injectées par `theme.inject_css()`)
    plutôt que trois composants Streamlit + un montage Plotly par tuile.
    À appeler à l'intérieur d'une colonne Streamlit (`with col:`).

    `delta_label` qualifie à quoi la variation se compare ("vs moyenne 30 j") :
    un « +9 ms » nu ne dit pas s'il s'agit d'hier, de la semaine passée ou de
    la baseline, et l'appelant est le seul à connaître la fenêtre réellement
    utilisée pour `prev`.

    `baseline` (normale personnelle 28 j) trace le repère pointillé de la
    sparkline. Fourni par l'appelant plutôt que recalculé ici : cette tuile ne
    voit que la fenêtre affichée, alors que la baseline se calcule sur
    l'historique complet jusqu'au jour choisi.

    Un `st.metric` brut n'a aucune hiérarchie visuelle et ne dit jamais si la
    valeur est bonne : la pastille répond à "45 ms de HRV, c'est bien ?" sans
    quitter la tuile, et l'infobulle (`title=`) reprend `metric.what` /
    `metric.how_read` du registre plutôt que de laisser deviner.

    `key` est accepté pour compatibilité d'appel (anciennement l'identifiant
    Streamlit du graphe Plotly de la sparkline) mais n'est plus utilisé : il
    n'y a plus de composant Plotly à identifier.
    """
    t = theme.active_tokens()
    status = _status_key_for_metric(metric, value, z)
    status_color_hex = status_hex(status, t)
    status_label = STATUS_LABELS[status]

    delta_str = None
    #: Écart nul UNE FOIS ARRONDI — à distinguer d'une comparaison impossible.
    #: Les deux donnent `delta_str is None`, mais l'un se tait et l'autre doit
    #: dire pourquoi il ne peut rien dire.
    delta_is_zero = False
    # Gris par défaut, couleur par EXCEPTION. Une pastille verte sur « FC repos
    # −3 » et rouge sur « HRV −16 » mélangeait deux logiques de jugement
    # inverses sur la même ligne, et colorait au passage des variations sans
    # sens bon/mauvais : une charge à −21 ou une dépense à −782 un jour de repos
    # sont des faits, pas de mauvaises nouvelles.
    #
    # Seules les clés de `metrics.SIGNAL_KEYS` (variabilité cardiaque, FC de
    # repos) portent de la couleur, et seulement quand l'écart va dans le
    # mauvais sens : ce sont les deux métriques dont un retard dit quelque chose
    # du corps quel qu'ait été le programme de la journée. Deux au maximum,
    # donc, sur toute la grille.
    delta_color_hex = t["ink_muted"]
    delta_note = ""
    if (
        value is not None and prev is not None
        and not (isinstance(value, float) and math.isnan(value))
        and not (isinstance(prev, float) and math.isnan(prev))
    ):
        diff = value - prev
        # Le signe et les cas particuliers (formats déjà signés, durées rendues
        # en heures) sont l'affaire du registre : `Metric.format_delta` est le
        # seul endroit qui décide comment une variation s'écrit.
        delta_str = metric.format_delta(diff)
        # Pas de pastille sur une variation NULLE une fois arrondie. « 0 vs ta
        # normale 28 j » occupe la place et la charge visuelle d'une variation
        # pour dire qu'il n'y en a pas — c'est la même faute qu'une pastille
        # verte « journée complète », et la tuile dit déjà sa valeur.
        #
        # Le test porte sur la chaîne AFFICHÉE et non sur `diff` : à l'écran,
        # un écart de 0,04 rendu « +0,0 » est un zéro, quoi qu'en dise la
        # virgule flottante.
        if not any(ch.isdigit() and ch != "0" for ch in delta_str):
            delta_str, delta_is_zero = None, True
        if delta_str is not None and metric.direction != 0 and diff != 0:
            is_good = (diff > 0) == (metric.direction > 0)
            delta_note = "en ta faveur" if is_good else "à ton désavantage"
            if not is_good and metric.key in metrics.SIGNAL_KEYS:
                delta_color_hex = status_hex("serious", t)
        elif metric.direction == 0:
            delta_note = "variation neutre : ni bonne ni mauvaise en soi"

    # Sparkline monochrome AU REPOS : huit tuiles de huit teintes différentes
    # faisaient croire à huit familles de métriques et rendaient la couleur
    # inutilisable pour signaler quoi que ce soit.
    #
    # Au SURVOL, elle prend sa couleur de métrique — celle qu'elle porte déjà
    # dans les graphes de série des autres pages (`metric.palette_index`), pour
    # qu'une teinte désigne partout la même grandeur. Le budget couleur tient
    # toujours : le survol ne concerne qu'une tuile à la fois, il est provoqué
    # par l'utilisateur, et il disparaît avec le curseur. Rien n'est coloré tant
    # que personne ne regarde.
    spark_color = t["ink_secondary"]
    # MÊME palette que `metric_chart` — c'est tout l'objet de la teinte de survol :
    # retrouver ailleurs la couleur de cette métrique. Lue dans `categorical`, la
    # tuile VO2max s'allumait en vert quand sa courbe est en cyan, et la promesse
    # tombait précisément sur la tuile qu'on venait de survoler.
    hot = t["series"][metric.palette_index % len(t["series"])]
    baseline_text = (
        f"Ligne pointillée : ta normale sur 28 jours ({metric.format(baseline)})"
        if baseline is not None and not (isinstance(baseline, float) and math.isnan(baseline))
        else ""
    )
    svg = _sparkline_svg(series, spark_color, baseline=baseline, baseline_text=baseline_text,
                         band=band)

    # Micro-repères d'échelle : sans eux, l'échelle automatique de la sparkline
    # donne exactement la même allure à une série qui varie de 2 % et à une qui
    # double. Deux nombres suffisent à rendre l'amplitude lisible.
    #
    # L'unité UNE FOIS, sur la borne haute seulement : sur la borne basse elle
    # est redondante (c'est la même grandeur, deux centimètres plus à gauche),
    # et répétée sur huit tuiles elle mettait huit « ml/kg/min » et huit
    # « kcal » à l'écran pour dire ce que le libellé disait déjà.
    # « min » et « max » ÉCRITS, et non déduits de la position.
    #
    # Posés nus aux deux bouts d'une ligne sous une courbe, les deux nombres se
    # lisaient comme un début et une fin de série. Le pire cas était réel : sur
    # la dépense du Bilan, « 1 622 » était à la fois la valeur du jour affichée
    # au-dessus et le minimum de la fenêtre — un lecteur y voyait une courbe qui
    # commence à sa valeur du jour. Deux mots de trois lettres lèvent
    # l'ambiguïté que douze pixels d'écart ne lèveront jamais.
    scale_html = ""
    s_valid = pd.Series(series).dropna() if series is not None else pd.Series(dtype=float)
    if len(s_valid) >= 2 and svg:
        lo_txt = metric.format(float(s_valid.min()), with_unit=False)
        hi_txt = metric.format(float(s_valid.max()))
        scale_html = (
            f'<div class="bevel-kpi-scale">'
            f'<span><i>min</i> {html.escape(lo_txt)}</span>'
            f'<span><i>max</i> {html.escape(hi_txt)}</span>'
            f"</div>"
        )

    label_html = html.escape(metric.short)
    value_html = html.escape(metric.format(value))
    # Infobulle sur UNE seule ligne : une ligne vide au milieu d'un attribut
    # HTML clôt le bloc HTML côté markdown Streamlit, et tout ce qui suit
    # (jusqu'au `">` fermant) est alors rendu comme du texte au-dessus de la
    # tuile. Les sauts de ligne sont donc aplatis, pas juste échappés.
    tooltip_html = html.escape(" ".join(f"{metric.what} — {metric.how_read}".split()))
    # Variation en pastille teintée plutôt qu'en texte coloré : à côté d'une
    # valeur en 1,5 rem, un simple bout de texte de 0,8 rem se lit comme la
    # suite de la valeur. Le fond translucide en fait un objet distinct.
    if delta_str is not None:
        pill_bg = _with_opacity(delta_color_hex, 0.14)
        pill_text = html.escape(f"{delta_str} {delta_label}".strip())
        pill_title = html.escape(f"{delta_str} {delta_label} — {delta_note}" if delta_note else "")
        delta_html = (
            f'<span class="bevel-kpi-pill" style="color:{delta_color_hex};background:{pill_bg}" '
            f'title="{pill_title}">{pill_text}</span>'
        )
    elif delta_is_zero:
        # Écart nul : AUCUNE pastille. « 0 vs ta normale 28 j » occupe la place
        # et la charge visuelle d'une variation pour annoncer qu'il n'y en a
        # pas — même faute qu'une pastille verte « journée complète ».
        #
        # Un espace RÉSERVÉ et non supprimé : la pastille tient une ligne de la
        # tuile, et l'ôter ferait remonter la sparkline d'une tuile sur quatre.
        # Une grille dont une case est plus courte que ses voisines se lit comme
        # un défaut de rendu, pas comme une absence de variation.
        delta_html = '<span class="bevel-kpi-pill" style="visibility:hidden">0</span>'
    else:
        # Dire POURQUOI il n'y a pas de variation : « pas de comparaison » ne
        # distingue pas une métrique jamais mesurée d'un historique encore trop
        # court pour porter une normale, alors que la conduite à tenir n'est
        # pas la même.
        delta_html = (
            f'<span class="bevel-kpi-pill" style="color:{t["ink_muted"]};'
            f'background:{_with_opacity(t["ink_muted"], 0.10)}" '
            f'title="Pas encore de normale calculable pour cette métrique : il faut '
            f'au moins cinq jours mesurés dans la fenêtre de 28.">'
            f"normale non calculable</span>"
        )

    # AUCUN marqueur de statut sur les tuiles. Il n'en restait qu'un à l'écran,
    # sur la variabilité cardiaque : un signe unique dans une grille de huit se
    # lit comme une anomalie d'affichage avant de se lire comme une information,
    # et personne ne peut deviner que les sept autres tuiles l'omettent parce
    # qu'elles vont bien. Le principe est le même que pour les pastilles : soit
    # toutes les tuiles portent un indicateur, soit aucune.
    #
    # Aucune information n'est perdue — ce que le glyphe signalait est dit en
    # toutes lettres, et plus tôt dans la page, par les nuances du verdict.
    # `status` reste calculé : il nomme l'état dans l'infobulle de la valeur.
    #
    # La tuile entière porte l'infobulle (survol n'importe où). Les quatre
    # variables `--bevel-spark*` y sont posées plutôt que sur le SVG : une
    # déclaration en style inline bat toute règle de feuille de style, et la
    # bascule au survol ne pourrait alors jamais l'emporter.
    st.markdown(
        f'<div class="bevel-kpi" title="{tooltip_html}" style="'
        f"--bevel-spark-cold:{spark_color};"
        f"--bevel-spark-cold-fill:{_with_opacity(spark_color, 0.12)};"
        f"--bevel-spark-hot:{hot};"
        f'--bevel-spark-hot-fill:{_with_opacity(hot, 0.18)}">'
        f'<div class="bevel-kpi-top">'
        f'<span class="bevel-kpi-label">{label_html}</span>'
        f"</div>"
        f'<div class="bevel-kpi-value" title="{html.escape(status_label)}">{value_html}</div>'
        f'<div class="bevel-kpi-delta">{delta_html}</div>'
        f"{svg}{scale_html}"
        f"</div>",
        unsafe_allow_html=True,
    )


def form_rail(value: float | None, ranges: list[tuple[float, float, str]],
              previous: float | None = None, zone_labels: dict[str, str] | None = None,
              previous_label: str = "il y a 7 j") -> str:
    """Réglette horizontale de position sur l'échelle de forme (bloc HTML).

    Remplace la jauge semi-circulaire, qui coûtait cher pour ce qu'elle disait :
    un arc de 100 px forçait ses trois noms de zone à s'étaler sur 250 px en
    laissant du vide à gauche, et le repère de la veille s'y réduisait à un
    trait de deux pixels sur une courbe. Une barre droite occupe toute la
    largeur utile, place chaque nom SOUS sa zone, et fait de la position une
    lecture immédiate de gauche à droite.

    Le repère fantôme (`previous`) est ce que la jauge ne pouvait pas montrer :
    « où j'en suis PAR RAPPORT À AVANT », qui est la vraie question une fois
    qu'on sait où l'on est.

    Rendu en HTML/CSS inline plutôt qu'en Plotly : il n'y a ici ni axe, ni
    échelle, ni interaction — seulement trois rectangles et deux repères, pour
    lesquels un graphe entier serait une machinerie sans emploi.
    """
    t = theme.active_tokens()
    if not ranges:
        return ""
    lo, hi = ranges[0][0], ranges[-1][1]
    span = (hi - lo) or 1.0

    def pct(v: float) -> float:
        return min(max((v - lo) / span, 0.0), 1.0) * 100

    # Chaque zone dans sa teinte de statut, très diluée : la réglette est UN
    # objet, une échelle continue, pas quatre pastilles. C'est le seul endroit
    # de la page où la couleur sert à situer plutôt qu'à alerter.
    #
    # Deux OPACITÉS par teinte, et non une seule : `critical`/`serious` partagent
    # la famille rouge et `good`/`excellent` la famille verte, si bien que quatre
    # paliers ne donnaient que deux bandes visibles — l'œil comptait deux zones
    # sous quatre étiquettes. Les extrêmes sont les plus soutenus : c'est aux
    # bouts de l'échelle qu'il importe de savoir qu'on a franchi quelque chose.
    ZONE_ALPHA = {"critical": 0.55, "serious": 0.26, "good": 0.26, "excellent": 0.55}
    segments = "".join(
        f'<div class="bevel-rail-zone" style="flex:{(r_hi - r_lo) / span};'
        f'background:{_with_opacity(status_hex(status_key, t), ZONE_ALPHA.get(status_key, 0.30))}"'
        "></div>"
        for r_lo, r_hi, status_key in ranges
    )

    labels = ""
    if zone_labels:
        for r_lo, r_hi, status_key in ranges:
            name = zone_labels.get(status_key, "")
            width = (r_hi - r_lo) / span
            # Une zone trop étroite pour son nom le laisse tomber plutôt que de
            # le tronquer ou de le superposer à sa voisine. Le seuil est bas
            # (12 %) parce qu'une zone anonyme est pire qu'un nom serré : elle
            # reste colorée, donc visible, et le lecteur cherche en vain à quoi
            # elle correspond.
            text = html.escape(name) if width >= 0.12 else ""
            labels += f'<div style="flex:{width};text-align:center">{text}</div>'

    markers = ""
    notes = ""
    if previous is not None and not (isinstance(previous, float) and math.isnan(previous)):
        # Le repère porte son nom EN CLAIR sous lui. Deux points sur une règle,
        # l'un plein l'autre creux, ne disent pas d'eux-mêmes lequel est
        # aujourd'hui : il fallait survoler pour l'apprendre, donc deviner
        # qu'il y avait quelque chose à survoler.
        markers += (
            f'<div class="bevel-rail-ghost" style="left:{pct(float(previous)):.2f}%" '
            f'title="{html.escape(previous_label)}"></div>'
        )
        notes = (
            f'<div class="bevel-rail-notes">'
            f'<div class="bevel-rail-ghost-label" style="left:{pct(float(previous)):.2f}%">'
            f"{html.escape(previous_label)}</div></div>"
        )
    if value is not None and not (isinstance(value, float) and math.isnan(value)):
        current = next((r[2] for r in ranges if r[0] <= value <= r[1]), "neutral")
        markers += (
            f'<div class="bevel-rail-cursor" style="left:{pct(float(value)):.2f}%;'
            f'background:{status_hex(current, t)}"></div>'
        )

    # Les zones dans leur propre boîte, les repères en frères : c'est elle qui
    # porte l'arrondi et le rognage des extrémités. Poser l'arrondi sur le
    # dernier ENFANT de la piste obligeait à compter les repères qui suivent —
    # un `nth-last-child(3)` qui devenait faux dès qu'on ajoutait un marqueur.
    return (
        f'<div class="bevel-rail">'
        f'<div class="bevel-rail-track">'
        f'<div class="bevel-rail-zones">{segments}</div>{markers}</div>'
        f'<div class="bevel-rail-labels">{labels}</div>'
        f"{notes}</div>"
    )


def gauge(
    value: float | None, ranges: list[tuple[float, float, str]], title: str = "",
    height: int = 220, unit: str = "", value_fmt: str | None = None,
    show_value: bool = True, zone_labels: dict[str, str] | None = None,
    previous: float | None = None,
) -> go.Figure:
    """Jauge pour une métrique bornée (forme/TSB, readiness...).

    `ranges` couvre tout l'axe : liste de (borne_basse, borne_haute, statut),
    `statut` étant une clé de statut ("critical"/"serious"/"good"/"excellent"/
    "neutral") -- la couleur vient du thème, jamais d'un hex écrit à l'appel.
    `value=None` (pas encore de mesure) donne une jauge vide plutôt qu'une
    exception.

    `value_fmt` est un format d3 (« +.0f », « .1f »...) : sans lui, Plotly
    affiche la valeur brute, d'où des « 7.42 » sur une jauge de forme où le
    centième n'a aucun sens physique.

    `show_value=False` ne dessine que l'anneau : l'appelant écrit alors la
    valeur lui-même (badge HTML), ce qui la met sous le contrôle du formatage
    Python plutôt que sous celui de Plotly.

    `zone_labels` ({clé de statut: nom lisible}) écrit le nom de chaque palier
    sous l'arc. Sans lui, l'anneau n'a ni graduation ni bornes et l'arc coloré
    derrière la valeur reste inexpliqué : personne ne peut deviner que la zone
    sombre à gauche est la surcharge.

    `previous` pose un trait fin à la valeur de la veille — la question qui
    suit immédiatement « où j'en suis » étant « et hier ? »."""
    t = theme.active_tokens()
    if not ranges:
        return _empty_figure(title, height, "Pas de plage définie pour cette jauge.")

    lo, hi = ranges[0][0], ranges[-1][1]
    # Paliers en ENCRE, d'une opacité croissante vers la droite, et non en
    # couleurs de statut : quatre arcs teintés derrière une aiguille colorée
    # font cinq objets colorés pour une seule information. Ce sont les noms de
    # zone (`zone_labels`) qui disent ce que chaque palier vaut ; l'arc ne fait
    # que les délimiter. Seule la valeur du jour porte la couleur.
    n_steps = max(1, len(ranges) - 1)
    steps = [
        dict(range=[r[0], r[1]], color=_with_opacity(t["ink_muted"], 0.10 + 0.10 * i / n_steps))
        for i, r in enumerate(ranges)
    ]
    threshold = None
    if previous is not None and not (isinstance(previous, float) and math.isnan(previous)):
        threshold = dict(
            line=dict(color=t["ink_muted"], width=2), thickness=0.85,
            value=min(max(float(previous), lo), hi),
        )
    if value is None or (isinstance(value, float) and math.isnan(value)):
        bar_color = t["ink_muted"]
        display_value = 0.0
    else:
        current = next((r[2] for r in ranges if r[0] <= value <= r[1]), "neutral")
        bar_color = status_hex(current, t)
        display_value = float(value)

    fig = go.Figure(go.Indicator(
        mode="gauge+number" if show_value else "gauge",
        value=display_value,
        number=dict(suffix=unit, valueformat=value_fmt,
                    font=dict(size=34, color=t["ink_primary"])),
        gauge=dict(
            # Anneau fin : les bornes chiffrées n'apportent rien (le codage
            # couleur suffit et l'appelant affiche déjà l'interprétation
            # textuelle sous la jauge), donc axe invisible.
            axis=dict(range=[lo, hi], visible=False),
            bar=dict(color=bar_color, thickness=0.22),
            bgcolor="rgba(0,0,0,0)", borderwidth=0,
            steps=steps,
            **({"threshold": threshold} if threshold else {}),
        ),
        title=dict(text=title, font=dict(size=14, color=t["ink_primary"])) if title else None,
    ))
    fig.update_layout(
        height=height, paper_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter Tight, system-ui, -apple-system, Segoe UI, sans-serif"),
        margin=dict(l=20, r=20, t=50 if title else 20, b=24 if zone_labels else 10),
    )
    if zone_labels:
        # Un nom par palier, posé sous l'arc à l'abscisse du MILIEU du palier
        # (l'indicateur Plotly occupe la moitié haute du domaine : x=0 à gauche
        # de l'arc, x=1 à droite). Les paliers trop étroits pour tenir un mot
        # sont omis plutôt que superposés à leur voisin.
        span = (hi - lo) or 1.0
        for r_lo, r_hi, status_key in ranges:
            label = zone_labels.get(status_key)
            if not label or (r_hi - r_lo) / span < 0.15:
                continue
            fig.add_annotation(
                text=label, showarrow=False, xref="paper", yref="paper",
                x=min(max(((r_lo + r_hi) / 2 - lo) / span, 0.0), 1.0), y=-0.02,
                xanchor="center", yanchor="top",
                font=dict(color=t["ink_muted"], size=10),
            )
    if value is None or (isinstance(value, float) and math.isnan(value)):
        fig.add_annotation(
            text="Pas de mesure récente", showarrow=False, xref="paper", yref="paper",
            x=0.5, y=0.12, font=dict(color=t["ink_muted"], size=12),
        )
    return fig


def form_trend(df: pd.DataFrame, date_col: str = "local_date", height: int = 150,
               days: int = 28, selected=None) -> go.Figure:
    """Mini-courbe fond (CTL) / fatigue (ATL) sur les derniers jours.

    La valeur de forme d'un seul jour ne dit pas grand-chose : c'est l'écart
    entre les deux courbes, et son sens de variation, qui expliquent le
    verdict. Cette courbe manquait complètement à la page du jour, qui
    n'affichait que le résultat final sans jamais montrer d'où il venait.

    Deux couleurs ici, et c'est le SEUL endroit du dashboard qui y a droit.
    Elles forment une paire sémantique, à ne pas dissocier ni réemployer :

        BLEU    le fond — la capacité construite
        ORANGE  la fatigue — ce qu'elle coûte en ce moment

    Ni axe Y ni légende : la valeur de chaque série est écrite au BOUT de sa
    courbe, dans sa couleur. C'est la seule graduation utile ici (l'unité de
    charge cardio n'a pas de sens physique à lire sur une règle), et elle
    supprime du même coup la légende du haut et la ligne de jargon du bas.
    """
    t = theme.active_tokens()
    if df is None or df.empty or "ctl" not in df.columns:
        return _empty_figure(None, height, "Pas encore de modèle de forme.")
    d = df.tail(days)
    fig = go.Figure()
    series = (
        ("ctl", "Fond", t["chart_pair"][0]),
        ("atl", "Fatigue", t["chart_pair"][1]),
    )
    for col, label, hue in series:
        fig.add_trace(go.Scatter(
            x=d[date_col], y=d[col], mode="lines", name=label,
            line=dict(color=hue, width=2),
            hovertemplate=f"{label} : %{{y:.1f}}<extra></extra>",
        ))
    fig.update_layout(**base_layout(None, None, height))
    fig.update_layout(
        showlegend=False,
        # Marge droite : elle loge les étiquettes de fin de ligne, qui sortent
        # de l'aire de tracé.
        margin=dict(l=0, r=74, t=8, b=0), hovermode="x unified",
    )
    # Grille horizontale presque invisible : elle guide l'œil sans devenir un
    # objet à part entière. Pas de graduation chiffrée -- voir la docstring.
    fig.update_yaxes(showgrid=True, gridcolor=_with_opacity(t["ink_primary"], 0.04),
                     zeroline=False, showticklabels=False)

    last_x = d[date_col].iloc[-1]
    for col, label, hue in series:
        last_y = d[col].iloc[-1]
        if pd.isna(last_y):
            continue
        fig.add_annotation(
            x=last_x, y=last_y, text=f"{label} {_fr_number(f'{last_y:.1f}')}",
            showarrow=False, xanchor="left", xshift=8, yanchor="middle",
            font=dict(color=hue, size=11),
        )

    # Repère du jour affiché : sans lui, la courbe se lit toujours comme
    # « aujourd'hui », alors qu'on peut être en train de regarder le 12.
    if selected is not None:
        fig.add_vline(x=pd.Timestamp(selected), line_width=1, line_dash="dot",
                      line_color=t["ink_muted"])
    return fr_date_axis(fig, d[date_col])


def distribution(
    series: pd.Series, baseline: float | None = None, title: str = "",
    y_title: str = "", color: str | None = None, height: int = 320,
) -> go.Figure:
    """Boîte à moustaches + nuage de points — forme totalement absente du
    dashboard aujourd'hui alors qu'une série de quelques dizaines de valeurs se
    résume très mal à une seule moyenne : cette vue montre dispersion et
    valeurs extrêmes d'un coup d'œil."""
    t = theme.active_tokens()
    color = color or t["categorical"][0]
    s = pd.Series(series).dropna() if series is not None else pd.Series(dtype=float)
    if s.empty:
        return _empty_figure(title, height, "Pas assez de valeurs pour une distribution.")

    fig = go.Figure()
    fig.add_trace(go.Box(
        y=s, name=title or "Distribution", boxpoints="all", jitter=0.4, pointpos=-1.8,
        marker=dict(color=color, size=5, opacity=0.5),
        line=dict(color=color), fillcolor=_with_opacity(color, 0.12),
        hovertemplate="%{y:.1f}" + (f" {y_title}" if y_title else "") + "<extra></extra>",
    ))
    if baseline is not None and not (isinstance(baseline, float) and math.isnan(baseline)):
        fig.add_hline(
            y=baseline, line_dash="dot", line_color=t["ink_muted"],
            annotation_text="Baseline", annotation_font_color=t["ink_muted"],
        )
    fig.update_layout(**base_layout(title, y_title, height))
    fig.update_xaxes(showticklabels=False)
    return fig


def calendar_heatmap(
    df: pd.DataFrame, value_col: str, date_col: str = "local_date", title: str = "",
    height: int = 220,
) -> go.Figure:
    """Grille semaine x jour de la semaine. Sur un historique de quelques
    semaines, la vue en ligne du temps noie l'assiduité dans le bruit
    quotidien ; la grille donne le motif hebdomadaire (quels jours décrochent)
    en un coup d'œil — idéal pour la sédentarité ou l'observance des séances."""
    if df is None or df.empty or value_col not in df.columns or df[value_col].dropna().empty:
        return _empty_figure(title, height, "Pas de données à cartographier.")

    d = df[[date_col, value_col]].dropna(subset=[date_col]).copy()
    d[date_col] = pd.to_datetime(d[date_col])
    d["dow"] = d[date_col].dt.weekday
    d["week_start"] = d[date_col] - pd.to_timedelta(d["dow"], unit="D")
    weeks = sorted(d["week_start"].unique())
    week_idx = {w: i for i, w in enumerate(weeks)}
    day_labels = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"]

    z = np.full((7, len(weeks)), np.nan)
    text = np.full((7, len(weeks)), "", dtype=object)
    for row in d.itertuples(index=False):
        i, j = int(getattr(row, "dow")), week_idx[getattr(row, "week_start")]
        val = getattr(row, value_col)
        z[i, j] = val
        date_label = getattr(row, date_col).strftime("%d/%m")
        text[i, j] = f"{date_label} : {val:.1f}" if pd.notna(val) else f"{date_label} : —"

    x_labels = [pd.Timestamp(w).strftime("%d/%m") for w in weeks]
    fig = go.Figure(go.Heatmap(
        z=z, x=x_labels, y=day_labels, text=text,
        colorscale=sequential_colorscale(), hovertemplate="%{text}<extra></extra>",
        showscale=True,
    ))
    fig.update_layout(**base_layout(title, None, height))
    fig.update_yaxes(autorange="reversed")
    return fig


def radar(values_by_group: dict[str, float], title: str = "", height: int = 360) -> go.Figure:
    """Équilibre des groupes musculaires. Réutilise l'ordre et les couleurs
    catégorielles fixes déjà utilisées par `muscle_group_bar` : un même groupe
    porte toujours la même couleur d'un graphe à l'autre du dashboard."""
    t = theme.active_tokens()
    groups = [g for g in MUSCLE_GROUP_ORDER if g in values_by_group
              and values_by_group[g] is not None
              and not (isinstance(values_by_group[g], float) and math.isnan(values_by_group[g]))]
    if not groups:
        return _empty_figure(title, height, "Pas de séries de renforcement sur cette période.")

    values = [values_by_group[g] for g in groups]
    labels = [MUSCLE_GROUP_LABELS[g] for g in groups]
    color = t["categorical"][0]

    fig = go.Figure()
    fig.add_trace(go.Scatterpolar(
        r=values + [values[0]], theta=labels + [labels[0]], fill="toself",
        fillcolor=_with_opacity(color, 0.15), line=dict(color=color, width=2),
        marker=dict(size=6, color=color),
        hovertemplate="%{theta} : %{r:.0f}<extra></extra>",
    ))
    fig.update_layout(
        polar=dict(
            bgcolor="rgba(0,0,0,0)",
            radialaxis=dict(showline=False, gridcolor=t["grid"], tickfont=dict(color=t["ink_muted"])),
            angularaxis=dict(gridcolor=t["grid"], tickfont=dict(color=t["ink_secondary"])),
        ),
        showlegend=False, height=height, paper_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter Tight, system-ui, -apple-system, Segoe UI, sans-serif", color=t["ink_secondary"]),
        title=dict(text=title, font=dict(size=14, color=t["ink_primary"])) if title else None,
        margin=dict(l=30, r=30, t=40 if title else 10, b=10),
    )
    return fig


def waterfall(components: list[tuple[str, float | None]], title: str = "", height: int = 340,
              unit: str = "", color: str | None = None) -> go.Figure:
    """Décomposition d'un score composite (ex : charge cardio du jour = charge
    de séance + charge de fond) en ses contributions, plus un total.

    Une seule teinte (`color`, par défaut la première catégorielle du thème),
    déclinée en opacité : contributions translucides, total plein. Les couleurs
    de STATUT sont volontairement exclues ici — l'ancien vert « increasing »
    était le vert « bon score » du thème, alors qu'accumuler de la charge
    cardio n'est ni bon ni mauvais en soi, et le total en gris passait pour la
    barre morte du graphe alors que c'est la seule valeur qu'on lit vraiment.

    Une contribution négative garde la même teinte mais reçoit des hachures :
    « ça retire au total » est une information de structure, pas un jugement,
    et ne mérite donc pas une couleur d'alerte.
    """
    t = theme.active_tokens()
    hue = color or t["categorical"][0]
    comps = [
        (label, v) for label, v in (components or [])
        if v is not None and not (isinstance(v, float) and math.isnan(v))
    ]
    if not comps:
        return _empty_figure(title, height, "Rien à décomposer sur cette période.")

    labels = [c[0] for c in comps] + ["Total"]
    values = [c[1] for c in comps]
    total = sum(values)
    measures = ["relative"] * len(comps) + ["total"]
    text = [f"{v:+.0f}{unit}" for v in values] + [f"{total:.0f}{unit}"]

    fig = go.Figure(go.Waterfall(
        x=labels, y=values + [total], measure=measures,
        increasing=dict(marker=dict(
            color=_with_opacity(hue, 0.45), line=dict(color=hue, width=1),
        )),
        decreasing=dict(marker=dict(
            # Même teinte, remplissage plus effacé : `marker.pattern` (des
            # hachures, qui auraient été plus explicites) n'existe pas sur une
            # trace Waterfall, et la bordure pleine suffit à distinguer la
            # barre qui retire de celle qui ajoute.
            color=_with_opacity(hue, 0.15), line=dict(color=hue, width=1),
        )),
        totals=dict(marker=dict(color=hue)),
        connector=dict(line=dict(color=t["baseline"], width=1)),
        text=text, textposition="outside",
        hovertemplate="%{x} : %{y:.1f}" + unit + "<extra></extra>",
    ))
    fig.update_layout(**base_layout(title, unit.strip() or None, height))
    return fig


def effort_bar(segments: list[tuple[str, float | None]],
               reference: list[tuple[str, float | None]] | None = None,
               *, scale_max: float | None = None, reference_label: str = "") -> str:
    """Répartition d'une durée d'effort par intensité, en HTML et non en Plotly.

    Remplace `load_bar` sur cette carte, et pour des raisons de rendu et non de
    goût : Plotly ne sait pas arrondir l'extrémité d'une barre empilée, ne sait
    pas poser une gouttière fixe de 2 px entre deux segments (son `bargap`
    travaille en fraction du domaine, donc en pixels variables), et ne réagit
    pas au survol par du CSS. Trois `<div>` font ici ce que 90 lignes de figure
    faisaient moins bien, sans embarquer de moteur de rendu pour dessiner trois
    rectangles.

    `reference` dessine SOUS la barre du jour la même répartition en moyenne,
    sur le même axe : sans elle, la carte montre une journée sans jamais dire si
    cette journée est ordinaire — la seule question que le lecteur se pose.

    Le partage d'axe est la condition de la comparaison. Les deux barres sont
    rapportées au même `scale_max`, faute de quoi deux répartitions de durées
    très différentes occuperaient la même largeur et se ressembleraient.

    Rendu en une chaîne plutôt qu'écrit dans Streamlit : le rendu HTML se teste
    sans lancer de serveur, et l'appelant décide où le poser.
    """
    t = theme.active_tokens()

    def _clean(items) -> list[tuple[str, float]]:
        return [
            (label, float(v)) for label, v in (items or [])
            if v is not None and not (isinstance(v, float) and math.isnan(v))
        ]

    day = _clean(segments)
    ref = _clean(reference)
    day_total = sum(v for _, v in day)
    ref_total = sum(v for _, v in ref)
    # L'axe NE S'ÉTIRE PAS pour contenir un jour hors norme : il est fixé par
    # l'appelant (90e centile des 90 derniers jours) et une journée qui le
    # dépasse remplit la barre, puis le dit avec un chevron. Étirer l'axe
    # reviendrait à écraser les 90 jours ordinaires pour faire de la place à
    # l'exception — et un jour exceptionnel doit se voir, pas se diluer.
    axis_max = float(scale_max) if scale_max else max(day_total, ref_total)
    if axis_max <= 0:
        return ""
    overflow = day_total > axis_max

    # Trois luminosités d'une SEULE teinte, du plus effacé au plus franc :
    # l'intensité de l'effort se lit alors dans l'intensité de la couleur, sans
    # avoir à consulter la légende. Trois teintes distinctes auraient suggéré
    # trois natures différentes là où il n'y a qu'une grandeur, graduée.
    #
    # Obtenues en composant l'accent sur la surface de la carte (`_with_opacity`)
    # plutôt qu'en écrivant trois hex : la rampe suit alors l'accent et le fond
    # du thème, au lieu de se figer sur les valeurs du sombre.
    alphas = [0.30, 0.65, 1.0]

    def _bar(items: list[tuple[str, float]], ghost: bool) -> str:
        # Un jour qui dépasse l'axe est ramené à sa propre somme : la barre est
        # alors pleine et les PROPORTIONS entre zones restent justes, ce qui est
        # ce qu'elle a encore à dire une fois qu'elle a atteint le bout.
        total = sum(v for _, v in items)
        denom = max(total, axis_max) if not ghost else axis_max
        cells = ""
        for i, (label, value) in enumerate(items):
            if value <= 0:
                continue
            share = value / denom
            alpha = alphas[min(i, len(alphas) - 1)]
            # Durée écrite DANS le segment au-delà de ~10 % de la largeur ;
            # en deçà, elle déborderait sur le voisin et se ferait rogner. La
            # légende sous la barre la porte de toute façon, pour tous.
            text = metrics.format_duration(value) if share >= 0.10 and not ghost else ""
            # Texte sombre sur le segment plein, clair sur les deux effacés :
            # au-dessus de ~0,8 d'opacité, l'accent est assez lumineux pour
            # qu'une encre claire y devienne illisible.
            ink = t["page"] if alpha >= 0.8 else t["ink_primary"]
            cells += (
                f'<span class="bevel-effort-seg" style="flex:0 0 {share * 100:.4f}%;'
                f'background:{_with_opacity(t["accent"], alpha)};color:{ink}" '
                f'title="{html.escape(label)} : {html.escape(metrics.format_duration(value))}">'
                f"{html.escape(text)}</span>"
            )
        klass = "bevel-effort-bar bevel-effort-ghost" if ghost else "bevel-effort-bar"
        # Chevron en bout de barre : il dit « ça continue au-delà de l'échelle »
        # sans mentir sur la longueur, là où une barre simplement pleine
        # laisserait croire qu'on est pile au maximum.
        tip = ""
        if not ghost and overflow:
            tip = ('<span class="bevel-effort-over" '
                   f'title="Au-delà de ton échelle habituelle ({metrics.format_duration(axis_max)})"'
                   ">›</span>")
        return f'<div class="{klass}">{cells}{tip}</div>'

    out = _bar(day, ghost=False)
    if ref and ref_total > 0:
        out += _bar(ref, ghost=True)
        out += f'<div class="bevel-effort-ref">{html.escape(reference_label)}</div>'

    # Légende sous la barre, et non dans un cartouche flottant : elle nomme des
    # segments dont certains font deux pixels de large et ne peuvent rien
    # porter. Chaque entrée redit la durée — c'est la seule lecture possible
    # pour les zones les plus courtes, qui sont justement les plus notables.
    # Les zones à zéro n'y figurent PAS : « Pic · 0 min » n'est pas une
    # information, c'est une case vide d'un formulaire. Sur une journée
    # ordinaire, deux des trois zones sont à zéro et la légende n'aurait plus
    # rien dit du tiers qui compte. L'indice de rampe reste celui de la ZONE et
    # non celui de la ligne, pour que la pastille garde la couleur du segment
    # qu'elle désigne.
    keys = ""
    for i, (label, value) in enumerate(day):
        if value <= 0:
            continue
        alpha = alphas[min(i, len(alphas) - 1)]
        keys += (
            f'<span class="bevel-effort-key">'
            f'<i style="background:{_with_opacity(t["accent"], alpha)}"></i>'
            f"{html.escape(label)}<b>{html.escape(metrics.format_duration(value))}</b></span>"
        )
    return f'<div class="bevel-effort">{out}<div class="bevel-effort-legend">{keys}</div></div>'


def intraday_hr(df: pd.DataFrame, zones_df: pd.DataFrame | None = None,
                 title: str = "Fréquence cardiaque", height: int = 320) -> go.Figure:
    """Courbe de FC intra-journalière avec bandes de zones personnelles
    (mart.hr_zones). `df` est déjà sous-échantillonné côté requête
    (`queries.heart_rate_intraday`) : sur ~37 000 échantillons/jour, envoyer le
    brut au navigateur ne montrerait rien de plus qu'une version sous-
    échantillonnée à l'échelle d'un graphe de quelques centaines de pixels."""
    if df is None or df.empty or "bpm" not in df.columns or df["bpm"].dropna().empty:
        return _empty_figure(title, height, "Pas de mesure de FC intra-journalière ce jour-là.")

    t = theme.active_tokens()
    d = df.dropna(subset=["bpm"]).sort_values("timestamp_local")
    fig = go.Figure()

    zone_status = ["good", "warning", "serious", "critical"]
    if zones_df is not None and not zones_df.empty:
        for row in zones_df.sort_values("zone_order").itertuples(index=False):
            min_bpm, max_bpm = getattr(row, "min_bpm"), getattr(row, "max_bpm")
            if pd.isna(min_bpm) or pd.isna(max_bpm):
                continue
            zone_order = int(getattr(row, "zone_order"))
            status_key = zone_status[min(zone_order - 1, len(zone_status) - 1)]
            fig.add_hrect(
                y0=min_bpm, y1=max_bpm, fillcolor=status_hex(status_key, t), opacity=0.06, line_width=0,
                annotation_text=str(getattr(row, "heart_rate_zone_type")).title(),
                annotation_position="right", annotation_font=dict(size=9, color=t["ink_muted"]),
            )

    fig.add_trace(go.Scatter(
        x=d["timestamp_local"], y=d["bpm"], mode="lines", name="FC",
        # Teinte d'identité et non `categorical[7]`, qui était le rouge du
        # critique : une courbe de FC intra-journalière rouge sur des zones
        # d'effort déjà colorées par statut faisait deux rouges de sens
        # différents sur le même graphe.
        line=dict(color=t["series"][metrics.require("resting_hr").palette_index], width=1),
        hovertemplate="%{x|%H:%M} : %{y:.0f} bpm<extra></extra>",
    ))
    fig.update_layout(**base_layout(title, "bpm", height))
    return fig


#: Aspect de chaque entrée de légende, en écho au trait qu'elle désigne :
#: une bande pour la zone normale, un filet fin pour le quotidien, un trait
#: épais pour la moyenne glissante.
LEGEND_KINDS = ("band", "thin", "thick")


def chart_header_html(meta: dict) -> str:
    """Titre, note de contexte et légende d'un graphe — EN HTML, au-dessus de la
    figure, jamais dedans.

    C'est la correction d'une collision de texte que trois réglages successifs
    n'avaient pas réglée, et ne pouvaient pas régler.

    Ces trois lignes vivaient dans la figure Plotly : le titre dans `layout.title`,
    la note en sous-titre ou en annotation `paper`, la légende en surimpression à
    `y=1.02`. Or Plotly ne dimensionne ses marges (`margin.autoexpand`) que pour
    le titre, la légende et les graduations — jamais pour les annotations — et il
    n'empile pas ces éléments : titre, sous-titre et légende visent la MÊME bande
    au-dessus du plot. Le seul graphe propre de la page « Progression » était le
    fond de forme, et pour une raison qui dit tout : c'est le seul sans note, donc
    le seul dont la bande n'était disputée par personne.

    Tant que ces lignes restent en coordonnées papier, chaque correction est un
    décalage à réajuster, qui recasse au premier changement de largeur de colonne.
    En HTML, elles retrouvent un flux vertical normal : trois blocs empilés par le
    navigateur, qui ne peuvent pas se chevaucher, et une classe CSS remplace les
    quatre réglages. La figure, elle, récupère toute sa boîte — ce qui règle du
    même coup la courbe qui débordait par le bas.
    """
    if not meta:
        return ""
    t = theme.active_tokens()
    parts = []
    if meta.get("title"):
        parts.append(f'<div class="bevel-chart-title">{html.escape(meta["title"])}</div>')
    if meta.get("note"):
        parts.append(f'<div class="bevel-chart-note">{html.escape(meta["note"])}</div>')
    keys = meta.get("keys") or []
    if keys:
        items = "".join(
            f'<span class="bevel-chart-key">'
            f'<i class="bevel-swatch bevel-swatch-{kind}" style="{"background" if kind == "band" else "color"}:{color}"></i>'
            f"{html.escape(label)}</span>"
            for label, kind, color in keys
        )
        parts.append(f'<div class="bevel-chart-legend">{items}</div>')
    return f'<div class="bevel-chart-head">{"".join(parts)}</div>' if parts else ""


def metric_block(df: pd.DataFrame, metric: Metric, *, decorate=None, **kwargs) -> None:
    """Le graphe COMPLET : son en-tête HTML, puis sa figure.

    Point d'entrée unique des pages. `metric_chart` reste la fabrique de la
    figure seule (utile aux tests, qui n'ont pas de contexte Streamlit), mais
    plus aucune page ne doit l'appeler directement : rendre la figure sans son
    en-tête laisserait un graphe sans titre ni légende, et c'est justement ce
    que la séparation rend possible.

    `decorate(fig)` — pour le seul appelant qui a quelque chose à ajouter à la
    figure (la ligne de métabolisme de base, page « Dépense »). Un point
    d'accroche explicite plutôt qu'un retour de figure : rendre la figure à
    l'appelant rouvrirait la porte à un `st.plotly_chart` sans en-tête.
    """
    fig = metric_chart(df, metric, **kwargs)
    if decorate is not None:
        decorate(fig)
    header = chart_header_html(dict(fig.layout.meta or {}))
    if header:
        st.markdown(header, unsafe_allow_html=True)
    st.plotly_chart(fig, width="stretch")


def chart_note_text(trend_result: stats.Trend | None, n: int | None = None) -> str:
    """Texte de la note : pente + IC, puis fiabilité, sur une seule ligne.

    Ne présente JAMAIS une tendance non significative comme une progression :
    `Trend.label()` bascule sur « aucune tendance détectable » dans ce cas — et
    pas sur « stable », qui affirmerait une pente nulle. Cette note ne s'habille
    jamais en vert/rouge non plus (encre neutre, significative ou non).
    """
    parts = []
    if trend_result is None:
        parts.append("Pas assez de points pour une tendance.")
    else:
        # `short_label` : le sous-titre d'un graphe est une surface de lecture,
        # pas un rapport. Le n, le p et l'intervalle vivent dans le détail
        # chiffré de la carte qui entoure ce graphe.
        parts.append(trend_result.short_label())
    if n is not None:
        note = stats.confidence_note(n)
        if note:
            parts.append(note)
    return " · ".join(parts)


def correlation_heatmap(
    corr_df: pd.DataFrame, labels: dict[str, str] | None = None,
    title: str = "Corrélations (paires significatives en couleur)", height: int | None = None,
) -> go.Figure:
    """Matrice de corrélation depuis `health.stats.corr_table` : grise les
    paires NON significatives au lieu de les colorer. Sur 18 métriques croisées
    sans correction, ~8 corrélations "significatives" à 5% sont attendues par
    pur hasard (cf. tests de stats.corr_table) — les colorer inciterait à leur
    donner un sens qu'elles n'ont pas."""
    if corr_df is None or corr_df.empty:
        return _empty_figure(title, height or 320, "Pas assez de paires pour une matrice de corrélation.")

    labels = labels or {}
    cols = sorted(set(corr_df["a"]) | set(corr_df["b"]))
    if not cols:
        return _empty_figure(title, height or 320, "Pas assez de paires pour une matrice de corrélation.")
    names = [labels.get(c, c) for c in cols]
    n = len(cols)
    idx = {c: i for i, c in enumerate(cols)}

    r_grid = np.full((n, n), np.nan)
    sig_grid = np.full((n, n), np.nan)
    for row in corr_df.itertuples(index=False):
        i, j = idx[row.a], idx[row.b]
        r_grid[i, j] = r_grid[j, i] = row.r
        if getattr(row, "is_significant", False):
            sig_grid[i, j] = sig_grid[j, i] = row.r
    for i in range(n):
        r_grid[i, i] = 1.0
        sig_grid[i, i] = 1.0

    t = theme.active_tokens()
    height = height or max(320, 40 * n + 60)
    text = [[f"r = {r_grid[i, j]:+.2f}" if not np.isnan(r_grid[i, j]) else "n/a" for j in range(n)]
            for i in range(n)]

    fig = go.Figure()
    # Fond neutre : toute paire part "non significative" (grise) par défaut.
    fig.add_trace(go.Heatmap(
        z=np.ones((n, n)), x=names, y=names, showscale=False,
        colorscale=[[0, t["grid"]], [1, t["grid"]]], hoverinfo="skip",
    ))
    # Paires significatives seules, en couleur, par-dessus (NaN = transparent,
    # laisse voir le fond gris).
    fig.add_trace(go.Heatmap(
        z=sig_grid, x=names, y=names, zmin=-1, zmax=1, text=text,
        colorscale=diverging_colorscale(), colorbar=dict(title="r"),
        hovertemplate="%{y} × %{x}<br>%{text}<extra></extra>",
    ))
    fig.update_layout(**base_layout(title, None, height))
    fig.update_yaxes(autorange="reversed")
    return fig

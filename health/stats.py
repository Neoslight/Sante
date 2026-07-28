"""Couche statistique : situer une valeur, mesurer une tendance, modéliser la forme.

Ce module existe pour une raison simple : une série brute ne dit rien. « HRV
45 ms » n'est interprétable que par rapport à SA propre normale, et « les pas
augmentent » n'est une information que si la pente est distinguable du bruit.

Trois principes tenus partout ici :

1. **Robustesse plutôt qu'élégance.** Médiane et MAD au lieu de moyenne et
   écart-type : sur 39 jours, une seule journée aberrante (jour partiel, sieste,
   maladie) déplace une moyenne et fausse tout ce qui en découle.

2. **Le calendrier, pas les lignes.** Toutes les fenêtres glissantes sont
   calendaires (`28D`), jamais positionnelles. `acwr_ratio` est NULL 11 jours
   sur 39 : une fenêtre de « 7 lignes » y couvre trois semaines réelles.

3. **Le n voyage avec le résultat.** Chaque fonction renvoie l'effectif utilisé
   et, quand c'est pertinent, un verdict de significativité. Avec 39 jours et
   6 semaines de données, la plupart des tendances ne sont PAS significatives —
   et le dashboard doit le dire au lieu de tracer une courbe rassurante.
"""
from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

# Constante de mise à l'échelle qui rend le MAD comparable à un écart-type
# pour une distribution normale.
MAD_TO_SIGMA = 1.4826

# Constantes de temps du modèle de forme (usage établi en entraînement
# d'endurance : Banister / TRIMP).
CTL_DAYS = 42  # « fitness » : charge chronique
ATL_DAYS = 7   # « fatigue » : charge aiguë


# --------------------------------------------------------------------------
# Baseline personnelle
# --------------------------------------------------------------------------
def rolling_baseline(
    df: pd.DataFrame, value_col: str, date_col: str = "local_date",
    window_days: int = 28, min_periods: int = 5,
) -> pd.DataFrame:
    """Médiane et dispersion glissantes sur une fenêtre CALENDAIRE.

    Renvoie les colonnes `baseline` (médiane), `mad`, `sigma` (MAD remis à
    l'échelle d'un écart-type), `lower`/`upper` (± 1 sigma) et `n_window`.
    C'est ce qui permet d'afficher une bande « ta normale » derrière chaque
    courbe, et donc de répondre à « est-ce que 45 ms, c'est bien ? ».
    """
    d = df[[date_col, value_col]].dropna(subset=[date_col]).sort_values(date_col).copy()
    d[date_col] = pd.to_datetime(d[date_col])
    roll = d.rolling(f"{window_days}D", on=date_col, min_periods=min_periods)[value_col]

    baseline = roll.median()
    # MAD glissant : median(|x - median(x)|) sur la même fenêtre.
    mad = roll.apply(lambda w: np.nanmedian(np.abs(w - np.nanmedian(w))), raw=True)
    sigma = mad * MAD_TO_SIGMA

    out = pd.DataFrame({
        date_col: d[date_col].to_numpy(),
        "value": d[value_col].to_numpy(),
        "baseline": baseline.to_numpy(),
        "mad": mad.to_numpy(),
        "sigma": sigma.to_numpy(),
        "n_window": roll.count().to_numpy(),
    })
    out["lower"] = out["baseline"] - out["sigma"]
    out["upper"] = out["baseline"] + out["sigma"]
    return out


#: Plafond du z-score. Au-delà, la valeur exacte n'a plus de sens : ce qui
#: compte est « très au-dessus de ta normale ». Évite aussi les infinis quand la
#: dispersion est nulle.
Z_CAP = 6.0


def robust_z(
    df: pd.DataFrame, value_col: str, date_col: str = "local_date",
    window_days: int = 28, min_periods: int = 5,
    baseline: pd.DataFrame | None = None,
) -> pd.Series:
    """Écart à sa propre normale, en nombre d'écarts-types robustes.

    |z| < 1 = dans la normale, 1-2 = notable, > 2 = franchement inhabituel.

    `baseline` : sortie de `rolling_baseline` déjà calculée pour cette même
    colonne. À passer chaque fois que l'appelant a besoin des DEUX — c'est le
    cas de toutes les tuiles KPI, qui affichent la baseline en pointillé et le
    z en couleur. Sans ce paramètre, la même médiane glissante était calculée
    deux fois par tuile, soit seize fois par grille, et la moitié de ce travail
    était jetée. Le résultat est identique ; seul le coût change.

    Cas limite important : quand la médiane et le MAD portent sur une série
    quasi constante, le MAD tombe à 0. Renvoyer 0 dans ce cas reviendrait à
    déclarer « normal » un point qui s'écarte d'une baseline parfaitement
    stable — exactement l'anomalie qu'on cherche à détecter. On retombe donc sur
    l'écart-type classique, puis, s'il est nul lui aussi, sur un z plafonné dont
    seul le signe est signifiant.
    """
    base = baseline if baseline is not None else rolling_baseline(
        df, value_col, date_col, window_days, min_periods,
    )
    deviation = base["value"] - base["baseline"]

    d = df[[date_col, value_col]].dropna(subset=[date_col]).sort_values(date_col).copy()
    d[date_col] = pd.to_datetime(d[date_col])
    fallback_sigma = (
        d.rolling(f"{window_days}D", on=date_col, min_periods=min_periods)[value_col]
        .std()
        .to_numpy()
    )

    sigma = base["sigma"].replace(0, np.nan)
    sigma = sigma.fillna(pd.Series(fallback_sigma, index=sigma.index)).replace(0, np.nan)

    z = deviation / sigma
    # Dispersion totalement nulle : le signe de l'écart reste la seule info.
    z = z.fillna(np.sign(deviation) * Z_CAP)
    return z.clip(-Z_CAP, Z_CAP).where(base["baseline"].notna())


def status_from_z(z: float | None, direction: int = 1) -> str:
    """Traduit un z-score en niveau de statut.

    `direction` : +1 si une valeur haute est bonne (HRV, VO2max), -1 si une
    valeur haute est mauvaise (FC de repos, sédentarité), 0 si neutre.
    Renvoie une des clés de `charts.STATUS` ou "neutral".
    """
    if z is None or (isinstance(z, float) and math.isnan(z)) or direction == 0:
        return "neutral"
    signed = z * direction
    if signed <= -2:
        return "critical"
    if signed <= -1:
        return "serious"
    if signed < 1:
        return "good"
    return "excellent"


# Libellé court + conduite à tenir, par niveau de TSB. Séparé des phrases de
# `tsb_status` : un badge de tête se lit en un mot ("Frais"), la phrase longue
# ne tient pas dedans et n'a plus sa place en tête de page.
TSB_BADGES: dict[str, tuple[str, str]] = {
    "critical": ("Surchargé", "Repos ou séance très légère aujourd'hui."),
    "serious": ("En charge", "Séance modérée, garde de la marge."),
    "good": ("Équilibré", "Charge et récupération se compensent."),
    "excellent": ("Frais", "Prêt pour un effort intense."),
    "neutral": ("Indéterminé", "Pas assez d'historique pour situer la forme."),
}

#: Conduite à tenir quand la forme est bonne MAIS qu'un signal est en retrait.
#: « Prêt pour un effort intense » sous une ligne « récupération en retrait »
#: était le dernier endroit où la page se contredisait encore : le verdict
#: tenait compte du signal, la recommandation non.
TEMPERED_HINT = "Effort modéré recommandé : la forme est là, la récupération non."


@dataclass(frozen=True)
class Verdict:
    """Le seul verdict d'état de la journée, nuances comprises.

    `nuances` porte les signaux qui méritent d'être dits (|z| >= 1), triés du
    plus marqué au moins marqué : (libellé, phrase de position, statut, z).
    """
    status: str
    headline: str
    hint: str
    nuances: list[tuple[str, str, str, float]]


#: Seuil à partir duquel un signal a quelque chose à dire. Aligné sur
#: `status_from_z` : en deçà, la valeur est dans la normale personnelle et
#: l'afficher revient à colorier du bruit.
NUANCE_Z = 1.0


def day_verdict(
    tsb: float | None, ctl: float | None,
    signals: dict[str, tuple[float | None, int]] | None = None,
) -> Verdict:
    """Un verdict unique pour la journée, à partir du modèle de forme et des
    signaux du jour.

    Le problème résolu ici est un problème d'affichage devenu un problème de
    fond : la page du jour tirait son état de quatre calculs indépendants
    (jauge TSB, z-scores par domaine, statut des tuiles, alertes de charge) et
    pouvait donc annoncer « Frais » et « récupération en berne » côte à côte
    sans jamais trancher. Tout passe désormais par ici.

    Règle de composition, volontairement simple à énoncer :

    * le **statut** vient toujours du TSB (`tsb_status`) — c'est la seule
      grandeur calculée ici de bout en bout, donc la seule vérifiable ;
    * la **phrase de tête** part du libellé de `TSB_BADGES` et se voit adjoindre
      la nuance dominante s'il en existe une défavorable (« Frais, mais
      récupération en retrait ») : deux affirmations opposées deviennent une
      seule phrase à concession ;
    * `nuances` ne retient que les signaux à |z| >= `NUANCE_Z`. Un jour sans
      rien à signaler renvoie une liste vide — c'est à l'appelant de ne rien
      afficher, pas d'écrire « rien à signaler ».

    `signals` : {libellé: (z, direction)}, direction au sens de
    `status_from_z` (+1 haut = mieux, -1 haut = moins bien, 0 neutre). Les
    signaux à direction nulle sont ignorés : sans sens bon/mauvais, un écart
    ne peut pas nuancer un verdict.
    """
    status, _ = tsb_status(tsb, ctl)
    label, hint = TSB_BADGES[status]

    nuances: list[tuple[str, str, str, float]] = []
    for name, (z, direction) in (signals or {}).items():
        if z is None or (isinstance(z, float) and math.isnan(z)) or direction == 0:
            continue
        if abs(z) < NUANCE_Z:
            continue
        nuances.append((name, z_phrase(z), status_from_z(z, direction), float(z)))
    nuances.sort(key=lambda n: abs(n[3]), reverse=True)

    # Seule une nuance DÉFAVORABLE contredit le badge : un jour frais avec une
    # HRV excellente n'a pas besoin d'un « mais ».
    adverse = [n for n in nuances if n[2] in ("serious", "critical")]
    if adverse:
        headline = f"{label}, mais {_concession(adverse[0][0], adverse[0][3])}"
        # La conduite à tenir suit le MÊME raisonnement que la phrase. Un TSB
        # frais autorise un effort intense seulement si rien ne dit le
        # contraire ; sur un statut déjà prudent (en charge, surchargé), la
        # consigne d'origine est plus conservatrice, on la garde.
        if status in ("good", "excellent"):
            hint = TEMPERED_HINT
    else:
        headline = label
    return Verdict(status=status, headline=headline, hint=hint, nuances=nuances)


def _lower_first(name: str) -> str:
    """Minuscule initiale pour insérer un libellé au milieu d'une phrase — SAUF
    si c'est un acronyme : « FC de repos » deviendrait « fC de repos ».
    La règle : une deuxième lettre majuscule signale un sigle, on n'y touche pas.
    """
    if len(name) > 1 and name[1].isupper():
        return name
    return name[0].lower() + name[1:]


def _concession(name: str, z: float) -> str:
    """Bout de phrase après « mais » : « récupération en retrait ».

    Écrit à part de `z_phrase` parce qu'une concession se lit à l'intérieur
    d'une phrase et doit rester courte — « mais récupération en dessous de ton
    niveau habituel » dépasse la ligne du badge.
    """
    subject = _lower_first(name)
    if abs(z) >= 2:
        return f"{subject} nettement en retrait" if z < 0 else f"{subject} nettement au-dessus"
    return f"{subject} en retrait" if z < 0 else f"{subject} au-dessus"


def z_phrase(z: float | None) -> str:
    """Traduit un z-score en français lisible, sans le chiffre.

    Volontairement SANS jugement de valeur (« au-dessus » plutôt que « bon ») :
    le sens bon/mauvais dépend de la métrique et est déjà porté par la couleur
    de statut de `status_from_z`. Cette phrase ne dit que la position par
    rapport à la normale personnelle, ce qui est la seule chose qu'un z-score
    signifie réellement.

    Seuils alignés sur ceux de `status_from_z` (1 et 2 écarts-types), pour que
    la phrase et la pastille ne racontent jamais deux histoires différentes.
    """
    if z is None or (isinstance(z, float) and math.isnan(z)):
        return "historique insuffisant"
    if abs(z) < 0.5:
        return "dans ta moyenne"
    if abs(z) < 1:
        return "légèrement au-dessus de ta moyenne" if z > 0 else "légèrement en dessous de ta moyenne"
    if abs(z) < 2:
        return "au-dessus de ton niveau habituel" if z > 0 else "en dessous de ton niveau habituel"
    return "très au-dessus de ta normale" if z > 0 else "très en dessous de ta normale"


# --------------------------------------------------------------------------
# Tendance
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Trend:
    """Résultat d'une régression linéaire, avec de quoi juger sa crédibilité."""
    slope_per_day: float
    slope_per_week: float
    intercept: float
    r2: float
    p_value: float
    ci_low_per_week: float
    ci_high_per_week: float
    n: int
    span_days: int

    @property
    def is_significant(self) -> bool:
        return self.n >= 10 and self.p_value < 0.05

    @property
    def direction(self) -> str:
        # « indéterminée » et non « stable » : le test ne rejette pas zéro, il
        # ne démontre pas zéro. Une vraie pente noyée sous le bruit produit
        # exactement le même p — les deux cas sont indiscernables ici, et le
        # mot choisi ne doit pas en trancher un.
        if not self.is_significant:
            return "indéterminée"
        return "hausse" if self.slope_per_day > 0 else "baisse"

    def short_label(self, unit: str = "", fmt: str = "{:+.2f}") -> str:
        """Même phrase, SANS l'appareil statistique — pour les surfaces de
        lecture (nuances du verdict, sous-titre de graphe).

        Un « p=0.36 » posé dans la ligne que l'utilisateur lit en premier ne lui
        apprend rien qu'il puisse utiliser : soit il sait ce qu'est une p-value
        et le détail chiffré lui est ouvert d'un clic, soit il ne le sait pas et
        le nombre ne fait que rendre la phrase illisible. La rigueur reste
        derrière — c'est `label()`, dans l'expander — pas devant.

        Toujours pas de « stable » ici non plus, pour la raison dite dans
        `direction` : ce serait affirmer une pente nulle que rien n'établit.
        """
        if self.n < 10:
            return "pas assez de mesures pour conclure"
        if not self.is_significant:
            return "aucune tendance nette"
        return f"{self.direction} de {fmt.format(self.slope_per_week)}{unit} par semaine"

    def label(self, unit: str = "", fmt: str = "{:+.2f}") -> str:
        """Phrase COMPLÈTE, avec n, p et l'intervalle — pour les détails
        chiffrés, jamais pour la ligne de tête (cf. `short_label`)."""
        if self.n < 10:
            return f"trop peu de points pour conclure (n={self.n})"
        if not self.is_significant:
            return f"aucune tendance détectable (n={self.n}, p={self.p_value:.2f})"
        val = fmt.format(self.slope_per_week)
        return (
            f"{self.direction} de {val}{unit}/semaine "
            f"(IC 95 % {self.ci_low_per_week:+.2f} à {self.ci_high_per_week:+.2f}, n={self.n})"
        )


def trend(
    df: pd.DataFrame, value_col: str, date_col: str = "local_date",
) -> Trend | None:
    """Régression linéaire de la métrique sur le temps.

    La pente est exprimée par semaine (lisible) alors que le calcul se fait en
    jours (correct même quand les points sont espacés irrégulièrement).
    Renvoie None s'il y a moins de 3 points exploitables.
    """
    d = df[[date_col, value_col]].dropna()
    if len(d) < 3:
        return None

    x = (pd.to_datetime(d[date_col]) - pd.to_datetime(d[date_col]).min()).dt.days.to_numpy(float)
    y = d[value_col].to_numpy(float)
    n = len(x)

    if np.ptp(x) == 0:
        return None

    slope, intercept = np.polyfit(x, y, 1)
    y_hat = slope * x + intercept
    ss_res = float(np.sum((y - y_hat) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0

    # Erreur-type de la pente, puis test de Student sur H0 : pente = 0.
    dof = n - 2
    if dof <= 0 or ss_res == 0:
        se_slope = 0.0
        p_value = 0.0
        t_crit = 0.0
    else:
        s_err = math.sqrt(ss_res / dof)
        se_slope = s_err / math.sqrt(float(np.sum((x - x.mean()) ** 2)))
        t_stat = slope / se_slope if se_slope > 0 else 0.0
        p_value = _t_two_sided_p(t_stat, dof)
        t_crit = _t_critical_95(dof)

    margin = t_crit * se_slope * 7
    return Trend(
        slope_per_day=float(slope),
        slope_per_week=float(slope * 7),
        intercept=float(intercept),
        r2=float(r2),
        p_value=float(p_value),
        ci_low_per_week=float(slope * 7 - margin),
        ci_high_per_week=float(slope * 7 + margin),
        n=int(n),
        span_days=int(np.ptp(x)) + 1,
    )


#: Effectif minimal pour qu'une pente ait le droit d'être qualifiée. Aligné sur
#: `Trend.is_significant` : en deçà, `trend` ne conclut jamais, et le verdict ne
#: doit pas non plus conclure « plateau » — un plateau est une AFFIRMATION, pas
#: l'absence de preuve.
PROGRESS_MIN_N = 10

#: Libellé de tête et statut, par état de progression. `serious` (et non
#: `warning`) parce que c'est le vocabulaire de statut du reste du module —
#: `status_from_z`, `tsb_status`, `charts.status_hex` partagent ces clés.
#: AUCUN état ne dit « plateau », et c'est délibéré. Un plateau affirme que la
#: pente est nulle ; une régression non significative n'affirme rien du tout —
#: elle constate que la mesure ne permet pas d'exclure zéro, ce qui est aussi le
#: cas d'une vraie pente noyée sous trop peu de points. Conclure « stable » à
#: partir d'un p élevé, c'est retourner une absence de preuve en preuve
#: d'absence, dans la seule ligne que le lecteur lit vraiment. L'affirmer
#: demanderait un test d'équivalence (intervalle de confiance entièrement
#: contenu dans une plage jugée négligeable) : il faudrait pour cela une borne
#: de non-pertinence par métrique, que le registre ne porte pas.
PROGRESS_BADGES: dict[str, tuple[str, str]] = {
    "up": ("Tu progresses", "good"),
    "down": ("En recul", "serious"),
    "mixed": ("Signaux contradictoires", "neutral"),
    "noise": ("Rien de mesurable", "neutral"),
    "unknown": ("Pas encore concluant", "neutral"),
}

PROGRESS_HINTS: dict[str, str] = {
    "up": "Au moins une pente monte dans le bon sens, au-delà du bruit.",
    "down": "Une pente descend dans le mauvais sens, au-delà du bruit.",
    "mixed": "Des pentes se distinguent du bruit, mais dans des sens opposés : "
             "aucune direction d'ensemble ne s'en dégage.",
    "noise": "Les pentes sont mesurées, aucune ne se distingue du bruit. Ce "
             "n'est pas un plateau : sur cette fenêtre, la mesure ne permet ni "
             "d'affirmer un progrès ni d'affirmer une stagnation.",
    "unknown": "Pas assez de points mesurés sur cette fenêtre pour qu'une "
               "régression dise quoi que ce soit.",
}

#: Conduite à tenir quand rien ne conclut, selon qu'il RESTE quelque chose à
#: élargir. « Élargis l'horizon » collé en dur à la fin du hint contredisait
#: l'écran dès que le sélecteur d'horizon disparaissait faute d'historique :
#: la page retirait le contrôle et conseillait dans la même seconde de s'en
#: servir. Le conseil dépend donc de la même condition que le sélecteur.
PROGRESS_ACTIONS: dict[bool, str] = {
    True: "Élargis l'horizon.",
    False: "Reviens dans quelques semaines : c'est du temps de mesure qu'il "
           "manque, pas un réglage.",
}
#: Les seuls états où un conseil a lieu d'être : quand une pente conclut, le
#: lecteur n'a rien à faire de plus que la lire.
PROGRESS_INCONCLUSIVE = ("noise", "unknown")


def merge_nuances(
    nuances: list[tuple[str, str, str, float]], span_days: int | None = None,
) -> list[tuple[str, str, str, float]]:
    """Fusionne en UNE ligne les nuances qui disent exactement la même chose.

    Trois lignes, trois puces et trois fois « aucune tendance nette » portent un
    seul bit d'information et occupent la place de trois signaux. C'est la règle
    déjà tenue ailleurs dans le tableau de bord — un bandeau « rien à signaler »
    est une alerte pour dire qu'il n'y a pas d'alerte — appliquée aux nuances.

    Le gain n'est pas seulement de la hauteur : une fois le motif régulier, le
    jour où une métrique se détache, c'est la RUPTURE du motif qui devient le
    signal. Trois lignes identiques n'ont pas ce pouvoir.

    Ne fusionne que des nuances de même phrase ET de même statut : deux pentes
    de valeurs différentes ont chacune quelque chose à dire. Le détail par
    métrique reste de toute façon dans le détail chiffré.
    """
    groups: dict[tuple[str, str], list[tuple[str, str, str, float]]] = {}
    for n in nuances:
        groups.setdefault((n[1], n[2]), []).append(n)

    out: list[tuple[str, str, str, float]] = []
    for (phrase, status), members in groups.items():
        if len(members) == 1:
            out.append(members[0])
            continue
        # Énumération à la française : virgules, puis « et » avant le dernier.
        # Seul le premier nom garde sa majuscule — les suivants sont au milieu
        # d'une phrase (`_lower_first` protège les sigles : « FC de repos »).
        names = [members[0][0]] + [_lower_first(m[0]) for m in members[1:]]
        joined = f"{', '.join(names[:-1])} et {names[-1]}"
        text = f"{phrase} sur {span_days} jours" if span_days else phrase
        out.append((joined, text, status, members[0][3]))
    return out


def progress_verdict(
    trends: dict[str, tuple[Trend | None, int]],
    primary: str | None = None,
    units: dict[str, str] | None = None,
    can_widen: bool = True,
) -> Verdict:
    """Un verdict unique de progression, à partir de plusieurs tendances.

    Pendant de `day_verdict` pour l'échelle longue : la page « Progression »
    empilait quatre graphes et laissait le lecteur composer lui-même la réponse
    à la question qu'elle pose en titre. Le sens d'une pente n'est pourtant PAS
    lisible sans le registre — une FC de repos qui baisse est une bonne
    nouvelle, une VO2max qui baisse une mauvaise — et sa crédibilité pas
    davantage.

    Règle de composition, dans cet ordre :

    * une pente ne compte QUE si elle est significative (`Trend.is_significant`,
      soit n >= `PROGRESS_MIN_N` et p < 0.05) ; sinon elle ne vaut rien, et un
      `Trend` absent ou trop court ne vaut même pas ce rien — la première est
      « mesurée mais indécise », le second « pas mesurable », et aucune des deux
      n'est un plateau (cf. `PROGRESS_BADGES`) ;
    * si `primary` est fourni et que cette tendance-là conclut, c'est elle qui
      donne la phrase de tête. Sinon, la somme des signes tranche : positive
      « tu progresses », négative « en recul », nulle avec des signes opposés
      « signaux contradictoires », et nulle faute de tout signal significatif
      « rien de mesurable » ;
    * une nuance défavorable ajoute sa concession à la phrase de tête, comme
      dans `day_verdict` (« Tu progresses, mais FC de repos en hausse »).

    `trends` : {libellé: (Trend | None, direction)}, direction au sens de
    `status_from_z` (+1 haut = mieux, -1 haut = moins bien, 0 neutre). Les
    directions nulles sont ignorées : sans sens bon/mauvais, une pente ne peut
    pas qualifier une progression.

    `can_widen` : y a-t-il encore un horizon à élargir ? Faux quand l'historique
    est trop court pour offrir plus d'une fenêtre — le conseil devient alors
    « reviens dans quelques semaines », sans quoi la page retire le sélecteur
    d'horizon et conseille dans la même seconde de s'en servir.

    `units` : {libellé: unité} pour la phrase de `Trend.label`. Le registre de
    métriques vit dans `health.metrics`, que ce module n'importe pas — c'est
    l'appelant qui connaît la métrique derrière chaque libellé.

    `nuances` porte (libellé, phrase, statut, pente par semaine) — même forme
    que `day_verdict`, pour que les deux cartes se rendent avec le même code.
    """
    units = units or {}
    nuances: list[tuple[str, str, str, float]] = []
    scores: dict[str, int] = {}

    for name, (tr, direction) in trends.items():
        if direction == 0:
            continue
        if tr is None or tr.n < PROGRESS_MIN_N:
            # Dit explicitement, et non omis : « pas assez de points » est une
            # information sur la fenêtre choisie, que l'utilisateur peut
            # corriger en élargissant l'horizon.
            nuances.append((name, "pas assez de mesures pour conclure",
                            "neutral", float("nan")))
            continue
        # `short_label` et non `label` : ces phrases sont la surface de lecture,
        # le n et le p vivent dans le détail chiffré.
        phrase = tr.short_label(units.get(name, ""))
        if not tr.is_significant:
            scores[name] = 0
            nuances.append((name, phrase, "neutral", tr.slope_per_week))
            continue
        score = 1 if (tr.slope_per_week > 0) == (direction > 0) else -1
        scores[name] = score
        nuances.append((name, phrase, "good" if score > 0 else "serious", tr.slope_per_week))

    # Attention d'abord, progrès ensuite, plateaux et non-concluants en dernier :
    # ce qui demande une décision se lit en haut de la carte.
    #
    # À statut égal, la métrique de référence passe devant. Sans ce départage,
    # la VO2max se retrouvait listée EN DERNIER alors qu'elle arbitre le
    # verdict : l'ordre affirmait le contraire de la règle de composition.
    _rank = {"serious": 0, "critical": 0, "good": 1, "neutral": 2}
    nuances.sort(key=lambda n: (
        _rank.get(n[2], 3),
        0 if n[0] == primary else 1,
        -abs(n[3]) if n[3] == n[3] else 0,
    ))

    if not scores:
        # Aucune pente n'a même pu être estimée : la fenêtre est trop courte.
        state = "unknown"
    elif primary is not None and scores.get(primary):
        state = "up" if scores[primary] > 0 else "down"
    elif not any(scores.values()):
        # Des pentes existent, aucune ne conclut. Distinct de `unknown` (la
        # fenêtre est assez longue, c'est l'amplitude qui manque) et surtout
        # distinct d'un plateau, qui serait une affirmation — cf. PROGRESS_BADGES.
        state = "noise"
    else:
        total = sum(scores.values())
        state = "up" if total > 0 else "down" if total < 0 else "mixed"

    headline, status = PROGRESS_BADGES[state]
    hint = PROGRESS_HINTS[state]
    # Le conseil n'est ajouté QUE si rien ne conclut, et il dit alors ce que
    # l'écran permet réellement de faire : `can_widen` doit refléter la présence
    # du sélecteur d'horizon chez l'appelant.
    if state in PROGRESS_INCONCLUSIVE:
        hint = f"{hint} {PROGRESS_ACTIONS[can_widen]}"

    adverse = [n for n in nuances if n[2] in ("serious", "critical")]
    if adverse and state == "up":
        headline = f"{headline}, mais {_lower_first(adverse[0][0])} va dans l'autre sens"
    return Verdict(status=status, headline=headline, hint=hint, nuances=nuances)


# --------------------------------------------------------------------------
# Modèle de forme (CTL / ATL / TSB)
# --------------------------------------------------------------------------
def ctl_atl_tsb(
    df: pd.DataFrame, load_col: str = "cardio_load_total",
    date_col: str = "local_date", ctl_days: int = CTL_DAYS, atl_days: int = ATL_DAYS,
) -> pd.DataFrame:
    """Modèle de forme à deux compartiments (Banister), sur la charge cardio.

    * **CTL** (Chronic Training Load, moyenne exponentielle 42 j) = la forme de
      fond, ce que l'entraînement a construit.
    * **ATL** (Acute Training Load, 7 j) = la fatigue récente.
    * **TSB** (Training Stress Balance) = CTL − ATL = la fraîcheur du jour.
      Positif : reposé. Négatif : en surcharge.

    Contrairement au readiness Fitbit, tout est calculable à la main depuis
    `cardio_load_total` — c'est la différence entre une boîte noire et une
    formule vérifiable.

    ATTENTION à `ctl_maturity` : une moyenne exponentielle sur 42 jours n'a pas
    de sens tant qu'on n'a pas 42 jours d'historique. Tant que cette colonne
    est < 1, le CTL est encore dominé par sa condition initiale et la courbe ne
    doit pas être présentée comme fiable.
    """
    d = df[[date_col, load_col]].dropna(subset=[date_col]).sort_values(date_col).copy()
    d[date_col] = pd.to_datetime(d[date_col])

    # Grille journalière continue : une journée sans séance est une vraie
    # journée de charge nulle, et le modèle doit la voir passer.
    full = pd.DataFrame({date_col: pd.date_range(d[date_col].min(), d[date_col].max(), freq="D")})
    full = full.merge(d, on=date_col, how="left")
    full[load_col] = full[load_col].fillna(0.0)

    # alpha = 1 - exp(-1/tau) : formulation continue, indépendante du pas.
    alpha_ctl = 1 - math.exp(-1 / ctl_days)
    alpha_atl = 1 - math.exp(-1 / atl_days)

    full["ctl"] = full[load_col].ewm(alpha=alpha_ctl, adjust=False).mean()
    full["atl"] = full[load_col].ewm(alpha=alpha_atl, adjust=False).mean()
    full["tsb"] = full["ctl"] - full["atl"]

    elapsed = np.arange(1, len(full) + 1)
    full["ctl_maturity"] = np.minimum(elapsed / ctl_days, 1.0)
    full["atl_maturity"] = np.minimum(elapsed / atl_days, 1.0)
    return full


def tsb_status(tsb: float | None, ctl: float | None) -> tuple[str, str]:
    """Lecture du TSB en (niveau, phrase). Seuils exprimés en % du CTL, car une
    même valeur absolue ne veut pas dire la même chose à 5 ou à 40 de charge."""
    if tsb is None or ctl is None or pd.isna(tsb) or pd.isna(ctl) or ctl <= 0:
        return "neutral", "Pas assez d'historique pour situer la forme."
    ratio = tsb / ctl
    if ratio < -0.5:
        return "critical", "Surcharge marquée : la fatigue récente dépasse largement ta base."
    if ratio < -0.2:
        return "serious", "En charge : normal en phase de progression, à ne pas prolonger."
    if ratio < 0.15:
        return "good", "Équilibre entre charge et récupération."
    return "excellent", "Frais : bon moment pour une séance difficile."


# --------------------------------------------------------------------------
# Dette de sommeil
# --------------------------------------------------------------------------
def sleep_debt(
    df: pd.DataFrame, minutes_col: str = "sleep_minutes_asleep",
    goal_col: str | None = "sleep_goal_minutes", default_goal: float = 480.0,
    date_col: str = "local_date", window_days: int = 14,
) -> pd.DataFrame:
    """Déficit de sommeil cumulé sur une fenêtre glissante, vs objectif réel.

    L'objectif vient de `sleep_goal_minutes` (fourni par Fitbit) quand il
    existe ; `default_goal` ne sert que de repli.
    """
    d = df[[c for c in (date_col, minutes_col, goal_col) if c]].copy()
    d[date_col] = pd.to_datetime(d[date_col])
    d = d.sort_values(date_col)

    goal = d[goal_col] if goal_col and goal_col in d else pd.Series(np.nan, index=d.index)
    d["goal"] = goal.fillna(default_goal)
    d["deficit"] = d["goal"] - d[minutes_col]
    d["debt"] = d.rolling(f"{window_days}D", on=date_col)["deficit"].sum()
    return d[[date_col, minutes_col, "goal", "deficit", "debt"]]


# --------------------------------------------------------------------------
# Corrélations honnêtes
# --------------------------------------------------------------------------
def corr_table(
    df: pd.DataFrame, columns: list[str], min_n: int = 20, fdr: float = 0.05,
) -> pd.DataFrame:
    """Corrélations par paires, avec n, p, et correction de Benjamini-Hochberg.

    Sans correction, croiser 18 métriques revient à tester 153 hypothèses : on
    s'attend alors à ~8 corrélations « significatives » purement dues au hasard.
    C'est exactement ce que produisait la matrice de corrélation d'origine.

    Renvoie une ligne par paire, triée par |r| décroissant, avec la colonne
    `is_significant` qui tient compte du nombre de tests effectués.
    """
    cols = [c for c in columns if c in df.columns]
    rows = []
    for i, a in enumerate(cols):
        for b in cols[i + 1:]:
            pair = df[[a, b]].dropna()
            n = len(pair)
            if n < min_n:
                rows.append({"a": a, "b": b, "r": np.nan, "n": n, "p_value": np.nan})
                continue
            x, y = pair[a].to_numpy(float), pair[b].to_numpy(float)
            if np.std(x) == 0 or np.std(y) == 0:
                rows.append({"a": a, "b": b, "r": np.nan, "n": n, "p_value": np.nan})
                continue
            r = float(np.corrcoef(x, y)[0, 1])
            dof = n - 2
            if abs(r) >= 1.0 or dof <= 0:
                p = 0.0
            else:
                t_stat = r * math.sqrt(dof / (1 - r * r))
                p = _t_two_sided_p(t_stat, dof)
            rows.append({"a": a, "b": b, "r": r, "n": n, "p_value": p})

    out = pd.DataFrame(rows)
    out["is_significant"] = _benjamini_hochberg(out["p_value"], fdr)
    out["abs_r"] = out["r"].abs()
    return out.sort_values("abs_r", ascending=False, na_position="last").drop(columns="abs_r")


def _benjamini_hochberg(p_values: pd.Series, fdr: float = 0.05) -> pd.Series:
    """Contrôle du taux de fausses découvertes sur une famille de tests."""
    result = pd.Series(False, index=p_values.index)
    valid = p_values.dropna().sort_values()
    m = len(valid)
    if m == 0:
        return result
    thresholds = np.arange(1, m + 1) / m * fdr
    passing = valid.to_numpy() <= thresholds
    if not passing.any():
        return result
    cutoff_rank = int(np.max(np.nonzero(passing)[0]))
    result.loc[valid.index[: cutoff_rank + 1]] = True
    return result


def lagged_correlation(
    df: pd.DataFrame, cause_col: str, effect_col: str, lags: range = range(0, 4),
    date_col: str = "local_date", min_n: int = 15,
) -> pd.DataFrame:
    """Corrélation entre une cause au jour J et un effet au jour J+lag.

    Généralise le `shift(-1)` charge → readiness du lendemain : permet de voir
    à quel décalage l'effet est le plus marqué (ou qu'il n'y en a aucun).
    """
    d = df[[date_col, cause_col, effect_col]].sort_values(date_col).copy()
    rows = []
    for lag in lags:
        pair = pd.DataFrame({
            "cause": d[cause_col],
            "effect": d[effect_col].shift(-lag),
        }).dropna()
        n = len(pair)
        if n < min_n or pair["cause"].std() == 0 or pair["effect"].std() == 0:
            rows.append({"lag_days": lag, "r": np.nan, "n": n, "p_value": np.nan})
            continue
        r = float(np.corrcoef(pair["cause"], pair["effect"])[0, 1])
        dof = n - 2
        t_stat = r * math.sqrt(dof / (1 - r * r)) if abs(r) < 1 else 0.0
        rows.append({"lag_days": lag, "r": r, "n": n, "p_value": _t_two_sided_p(t_stat, dof)})
    out = pd.DataFrame(rows)
    out["is_significant"] = _benjamini_hochberg(out["p_value"])
    return out


# --------------------------------------------------------------------------
# Fiabilité affichable
# --------------------------------------------------------------------------
def outside_band_since(
    df: pd.DataFrame, col: str, date_col: str = "local_date", min_days: int = 5,
) -> tuple[dt.date, int] | None:
    """Depuis quand la série est-elle SORTIE de sa zone normale, et par où ?

    Renvoie `(date de sortie, sens)` — sens -1 sous la bande, +1 au-dessus — ou
    `None` si la dernière valeur est dans sa zone, ou si la sortie est trop
    récente pour valoir d'être dite.

    Existe pour un cas précis : sur le fond de forme, la courbe passait sous sa
    zone normale sur tout le dernier tiers de la fenêtre, et c'était LE fait de
    la page — mais rien ne l'énonçait. Sortir d'une bande ± 1 sigma n'est pas une
    inférence : c'est une comparaison entre deux séries tracées l'une sur
    l'autre, que le lecteur fait déjà des yeux. La nommer ne fait que lui
    épargner de compter les jours à rebours sur l'axe.

    `min_days` écarte les sorties d'un ou deux jours, qui ne sont que le bruit
    ordinaire d'une série contre sa propre dispersion.

    Note sur ce que cette fonction NE détecte pas : un décalage constant finit
    par entrer dans la médiane glissante et devient la nouvelle normale au bout
    de 28 jours. C'est le comportement voulu d'une baseline personnelle — le cas
    qu'on veut attraper est celui d'une série qui s'éloigne PLUS VITE que sa
    propre référence ne la suit.
    """
    if df is None or df.empty or col not in df.columns:
        return None
    base = rolling_baseline(df, col, date_col=date_col)
    d = base.dropna(subset=["baseline", "lower", "upper"])
    if d.empty:
        return None

    last = d.iloc[-1]
    if last["value"] < last["lower"]:
        direction, bound = -1, "lower"
    elif last["value"] > last["upper"]:
        direction, bound = 1, "upper"
    else:
        return None

    # Remonter tant que la série reste du même côté : la date de sortie est le
    # premier jour de la série ININTERROMPUE en cours, pas la première sortie
    # de l'historique.
    out = (d["value"] < d[bound]) if direction < 0 else (d["value"] > d[bound])
    start = len(d) - 1
    while start > 0 and bool(out.iloc[start - 1]):
        start -= 1
    if len(d) - start < min_days:
        return None
    return pd.Timestamp(d[date_col].iloc[start]).date(), direction


#: Réserves de fiabilité par palier d'effectif : (seuil, forme courte, forme
#: longue). La courte va aux surfaces de lecture, la longue aux détails chiffrés.
_CONFIDENCE_TIERS: list[tuple[int, str, str]] = [
    (10, "trop peu pour conclure", "trop peu pour conclure"),
    (28, "tendance indicative", "tendance indicative"),
    (90, "historique encore court", "tendance plausible, historique encore court"),
]


def confidence_note(n: int) -> str:
    """La réserve de fiabilité SEULE, sans l'effectif — pour les surfaces de
    lecture, où « n=37 » n'apprend rien à qui ne compte pas les jours.

    Chaîne vide au-delà de 90 points : il n'y a alors aucune réserve à émettre,
    et une mention « historique suffisant » serait une alerte pour dire qu'il
    n'y a pas d'alerte.
    """
    for threshold, short, _long in _CONFIDENCE_TIERS:
        if n < threshold:
            return short
    return ""


def confidence_label(n: int, unit: str = "jours") -> str:
    """Mention de fiabilité AVEC l'effectif, pour les détails chiffrés."""
    for threshold, _short, long in _CONFIDENCE_TIERS:
        if n < threshold:
            return f"n={n} {unit} — {long}"
    return f"n={n} {unit}"


# --------------------------------------------------------------------------
# Loi de Student, sans dépendance externe
# --------------------------------------------------------------------------
def _t_two_sided_p(t_stat: float, dof: int) -> float:
    """p bilatérale de la loi de Student, via la fonction bêta incomplète."""
    if dof <= 0:
        return 1.0
    t2 = float(t_stat) ** 2
    return _betainc(0.5 * dof, 0.5, dof / (dof + t2))


def _t_critical_95(dof: int) -> float:
    """Quantile 97,5 % de la loi de Student (bissection sur la p-value)."""
    if dof <= 0:
        return 0.0
    lo, hi = 0.0, 100.0
    for _ in range(80):
        mid = (lo + hi) / 2
        if _t_two_sided_p(mid, dof) > 0.05:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def _betainc(a: float, b: float, x: float) -> float:
    """Fonction bêta incomplète régularisée I_x(a, b) (fraction continue de
    Lentz). Suffisant et stable pour les tailles d'échantillon en jeu ici, et
    évite d'ajouter SciPy pour deux p-values."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    ln_beta = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
    front = math.exp(ln_beta + a * math.log(x) + b * math.log1p(-x))
    if x >= (a + 1) / (a + b + 2):
        return 1.0 - _betainc(b, a, 1 - x)
    return front * _beta_cf(a, b, x) / a


def _beta_cf(a: float, b: float, x: float, max_iter: int = 300, eps: float = 1e-12) -> float:
    tiny = 1e-30
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    if abs(d) < tiny:
        d = tiny
    d = 1.0 / d
    h = d
    for m in range(1, max_iter + 1):
        m2 = 2 * m
        num = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + num * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + num / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        h *= d * c

        num = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + num * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + num / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


# =============================================================================
# Fonctions déplacées depuis app/Bilan_du_jour.py
#
# Elles y étaient pures mais intestables : une page Streamlit ne s'importe pas,
# et le seul filet qu'elles avaient était un test de fumée qui vérifie l'absence
# d'exception. Trois cent lignes de règles — seuils, fenêtres, bornes d'axe —
# ne peuvent pas reposer sur « ça n'a pas planté ».
#
# Le découpage suit une ligne simple : ce qui DÉCIDE vit ici, ce qui FORMULE
# reste dans la page. `resting_hr_drift` renvoie un nombre d'écarts-types, pas
# une phrase ; `long_term_reference` renvoie un recul en jours, pas « sur 3 mois ».
# =============================================================================

#: Bornes de la réglette de forme, en fraction du CTL. Ce sont des RATIOS PURS :
#: l'axe ne doit pas dépendre de la valeur du jour, sinon le curseur se déplace
#: quand on navigue d'un jour à l'autre alors que la forme n'a pas bougé, et le
#: repère « il y a 7 jours » se retrouve posé sur une règle qui n'est pas la
#: sienne.
TSB_RAIL_BOUNDS = (-0.8, -0.5, -0.2, 0.15, 0.5)
TSB_RAIL_STATUSES = ("critical", "serious", "good", "excellent")


def tsb_rail_ranges(
    tsb: float | None, ctl: float | None,
    fallback_good: tuple[float, float] = (-10.0, 10.0),
) -> list[tuple[float, float, str]]:
    """Paliers de la réglette de forme : [(borne_basse, borne_haute, statut)].

    Aux mêmes ratios que `tsb_status`, pour que la réglette et le texte du
    verdict racontent la même histoire.

    `tsb` n'entre PAS dans le calcul — il n'est accepté que pour que la
    signature dise ce que la fonction prend en compte, et le paramètre reste
    volontairement inutilisé : c'est précisément parce qu'il servait à étirer
    l'axe que la règle changeait de graduation à chaque jour affiché.

    `fallback_good` sert quand le CTL n'est pas encore exploitable (historique
    trop court, CTL nul ou négatif) : on retombe alors sur la plage cible fixe
    du registre de métriques.
    """
    if ctl is None or pd.isna(ctl) or ctl <= 0:
        lo, hi = fallback_good
        span = hi - lo
        bounds = [lo - 2 * span, lo, 0.0, hi, hi + span]
    else:
        bounds = [r * ctl for r in TSB_RAIL_BOUNDS]
    return [
        (bounds[i], bounds[i + 1], TSB_RAIL_STATUSES[i])
        for i in range(4) if bounds[i + 1] > bounds[i]
    ]


def long_term_reference(
    df: pd.DataFrame, value_col: str, as_of, lag_days: int = 90,
    half_window: int = 7, min_lag_days: int = 28, date_col: str = "local_date",
) -> tuple[float | None, int]:
    """Niveau de `value_col` il y a ~`lag_days` jours, et le recul RÉELLEMENT
    obtenu — `(None, 0)` si l'historique est trop court pour dire quoi que ce soit.

    Pour les métriques à variation lente (VO2max), qu'une moyenne sur la fenêtre
    affichée ne fait que comparer à son propre bruit d'estimation.

    Deux garde-fous, et le second est le plus important :

    * la référence est la MÉDIANE d'une fenêtre de ±`half_window` jours autour
      du jour visé, pas sa valeur isolée — comparer deux points uniques d'une
      série bruitée fabrique une tendance à partir de deux accidents ;
    * quand l'historique est plus court que `lag_days`, on recule aussi loin
      qu'il le permet et on RENVOIE ce recul, pour que l'appelant l'annonce.
      Un libellé « sur 3 mois » devant un écart calculé sur cinq semaines est un
      mensonge qu'aucun lecteur ne peut détecter.
    """
    if value_col not in df.columns or date_col not in df.columns:
        return None, 0
    hist = df[[date_col, value_col]].dropna()
    if hist.empty:
        return None, 0
    days = pd.to_datetime(hist[date_col]).dt.date
    ref = min(as_of - dt.timedelta(days=lag_days), days.max())
    ref = max(ref, days.min() + dt.timedelta(days=half_window))
    lag = (as_of - ref).days
    if lag < min_lag_days:
        return None, 0
    window = hist.loc[
        (days >= ref - dt.timedelta(days=half_window))
        & (days <= ref + dt.timedelta(days=half_window))
    ]
    if window.empty:
        return None, 0
    return float(window[value_col].median()), lag


#: Fenêtres de la dérive de FC de repos. Cinq jours récents parce qu'une seule
#: nuit ne dit rien ; vingt-huit jours de référence parce que c'est la fenêtre
#: de normalité employée partout ailleurs.
RHR_RECENT_DAYS = 5
RHR_REF_DAYS = 28
#: En deçà, la médiane et le MAD de la référence portent sur trop peu de nuits.
RHR_REF_MIN_DAYS = 20


def resting_hr_drift(
    series: pd.Series, recent_days: int = RHR_RECENT_DAYS,
    ref_days: int = RHR_REF_DAYS, min_ref_days: int = RHR_REF_MIN_DAYS,
) -> tuple[float, float, float] | None:
    """Dérive de la FC de repos : `(moyenne récente, médiane de référence,
    écart en sigmas robustes)`, ou `None` s'il n'y a pas de quoi conclure.

    Fenêtre GLISSANTE des deux côtés. La référence était « tout l'historique
    sauf les cinq derniers jours » : à 39 jours cela comparait 5 jours à 34,
    dans un an cela en aurait comparé 5 à 360. Une moyenne à vie ne bouge plus,
    et la règle se serait figée — toujours vraie ou jamais — sans que rien ne
    le signale.

    L'écart est rendu en SIGMAS et non en battements : un seuil de « +3 bpm »
    codé en dur est un seuil pour quelqu'un dont la FC de repos varie de 3 bpm,
    et du bruit permanent pour quelqu'un dont elle varie de 6. Le sigma est
    robuste (MAD remis à l'échelle), donc insensible aux quelques nuits de
    fièvre ou de mauvaise mesure qui gonfleraient un écart-type nu.

    C'est à l'appelant de fixer le seuil au-delà duquel il alerte : cette
    fonction mesure, elle ne juge pas.
    """
    s = pd.Series(series).dropna()
    recent_window = s.tail(recent_days)
    ref_window = s.iloc[-(recent_days + ref_days):-recent_days]
    if len(recent_window) < recent_days or len(ref_window) < min_ref_days:
        return None
    recent = float(recent_window.mean())
    base = float(ref_window.median())
    sigma = float((ref_window - base).abs().median()) * MAD_TO_SIGMA
    if sigma <= 0:
        return None
    return recent, base, (recent - base) / sigma

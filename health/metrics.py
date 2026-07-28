"""Registre des métriques : une définition unique par indicateur.

Ce module est la réponse au reproche « tout est vague ». Avant, chaque page
recopiait à la main le titre, l'unité et la couleur de chaque graphe : rien ne
disait ce que la métrique mesure, d'où elle vient, ni si la valeur affichée est
bonne. Résultat, 21 graphiques de séries brutes sans point de repère.

Désormais un seul objet `Metric` alimente le titre du graphe, l'unité de l'axe,
le format du survol, le libellé et l'infobulle des tuiles KPI, la couleur de
statut et la page Glossaire. Ajouter une métrique au dashboard = ajouter une
entrée ici.

Distinction volontairement explicite dans `provenance` : certaines valeurs sont
des **mesures** (pas, FC, minutes de sommeil), d'autres des **scores
propriétaires Fitbit** non reproductibles (readiness, score de sommeil, charge
cardio, ACWR), d'autres enfin sont **calculées ici** avec une formule
vérifiable (CTL/ATL/TSB, BMR, z-scores). L'utilisateur doit pouvoir distinguer
une boîte noire d'un calcul auditable.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Familles, dans l'ordre de lecture du dashboard.
FAMILIES: dict[str, str] = {
    "forme": "Forme & récupération",
    "cardio": "Cardio & charge",
    "sommeil": "Sommeil",
    "activite": "Activité & dépense",
    "renfo": "Renforcement",
    "qualite": "Qualité des données",
}

# Provenances possibles, avec leur niveau de confiance affichable.
PROV_MEASURE = "Mesure de l'appareil"
PROV_FITBIT_SCORE = "Score propriétaire Fitbit (non reproductible)"
PROV_FITBIT_DAILY = "Agrégat quotidien Fitbit"
PROV_COMPUTED = "Calculé ici"


@dataclass(frozen=True)
class Metric:
    """Tout ce qu'il faut savoir pour afficher ET comprendre une métrique."""

    key: str                    # nom de colonne dans mart.daily (ou mart.weekly)
    label: str                  # libellé complet, pour un titre de graphe
    short: str                  # libellé court, pour une tuile KPI
    unit: str                   # unité affichée ("bpm", " ms", " min"...)
    family: str
    what: str                   # ce que la métrique mesure, en une phrase
    how_read: str               # comment l'interpréter, ce qui la fait bouger
    provenance: str
    fmt: str = "{:.0f}"
    direction: int = 0          # +1 : haut = mieux, -1 : haut = moins bien, 0 : neutre
    baseline: str = "personal"  # "personal" | "target" | "fixed" | "none"
    target: float | None = None
    good_range: tuple[float, float] | None = None
    ma_window: int = 7
    palette_index: int = 0      # index dans theme.active_tokens()["series"], la
                                # palette d'IDENTITÉ — distincte de `categorical`,
                                # qui empiétait sur le budget de statut (vert
                                # « bon », rouge « critique »). La couleur reste
                                # une affaire de présentation, pas de sémantique :
                                # c'est précisément pourquoi elle ne doit jamais
                                # emprunter les teintes qui, elles, en portent une.
    aliases: tuple[str, ...] = field(default_factory=tuple)

    def format(self, value: float | None, with_unit: bool = True) -> str:
        """Valeur formatée à la française, unité comprise par défaut.

        `with_unit=False` sert aux étiquettes qui accompagnent une valeur déjà
        unitée (les bornes min/max sous une sparkline) : « 50,4 » et « 54,2 »
        sous un « 53,7 ml/kg/min » se lisent sans ambiguïté, alors que trois
        « ml/kg/min » sur la même tuile débordent de la carte.
        """
        if value is None:
            return "—"
        try:
            if value != value:  # NaN
                return "—"
        except TypeError:
            return "—"
        if self.fmt in (FMT_DURATION, FMT_DURATION_SIGNED):
            return format_duration(value, signed=self.fmt == FMT_DURATION_SIGNED)
        return _fr_number(self.fmt.format(value)) + (self.unit if with_unit else "")

    def format_delta(self, diff: float) -> str:
        """Variation formatée, toujours signée.

        Séparé de `format` parce qu'une variation se lit signée même quand la
        valeur ne l'est pas (« +25 min » vs « 465 min »), et parce que les
        formats déjà signés du registre (`tsb`, `sleep_debt`,
        `skin_temp_deviation_c`) produiraient « ++2.0 » si on préfixait
        aveuglément un « + ».
        """
        if self.fmt in (FMT_DURATION, FMT_DURATION_SIGNED):
            return format_duration(diff, signed=True)
        out = _fr_number(self.fmt.format(diff))
        if diff > 0 and not out.startswith(("+", "-")):
            out = "+" + out
        return out

    @property
    def direction_label(self) -> str:
        return {1: "plus haut = mieux", -1: "plus bas = mieux", 0: "neutre"}[self.direction]


# Format sentinelle : la valeur est un nombre de minutes à rendre en heures et
# minutes. Une chaîne `str.format` ne peut pas exprimer « 465 -> 7 h 45 min »,
# d'où ce marqueur reconnu par `Metric.format`. L'`unit` (" min") reste
# renseignée sur ces métriques : elle ne sert plus à l'affichage de la valeur
# mais bien au titre d'axe des graphes (`charts.series`).
FMT_DURATION = "{duration}"
# Même chose pour une durée dont le signe fait partie de l'information (une
# dette de sommeil de −2 h et de +2 h ne se lisent pas pareil).
FMT_DURATION_SIGNED = "{duration:+}"


# Séparateur de milliers français : espace INSÉCABLE ordinaire (U+00A0) et non
# l'espace fine (U+202F) que recommande la typographie. Sous 0,7 rem, l'espace
# fine ne fait que deux pixels : dans les micro-étiquettes d'une sparkline,
# « 15 031 » s'y lisait « 15031 », c'est-à-dire un tout autre nombre. Insécable
# dans les deux cas, pour que le nombre ne se coupe jamais en fin de ligne.
FR_THIN_SPACE = " "


def _fr_number(text: str) -> str:
    """Convertit un nombre formaté à l'anglaise en écriture française.

    `"{:,.0f}".format(15031)` donne « 15,031 », que l'œil francophone lit
    d'abord comme « quinze virgule zéro trente-et-un ». Le passage se fait sur
    la chaîne déjà formatée, en un seul point du code : les gabarits du
    registre restent des formats Python standard, et aucune page n'a à
    connaître la convention typographique.
    """
    return text.replace(",", FR_THIN_SPACE).replace(".", ",")


def format_duration(minutes: float, signed: bool = False) -> str:
    """465 -> « 7 h 45 min ». Lire une durée de sommeil en minutes brutes
    demande une division mentale à chaque coup d'œil ; c'est exactement ce que
    la règle des 3 secondes interdit.

    Arrondi à la minute avant découpage, sinon 479,6 min donnerait « 7 h 59 »
    au lieu de « 8 h ». Sous l'heure, la mention des heures est omise (« 45
    min ») plutôt que rendue en « 0 h 45 min ».
    """
    total = int(round(abs(minutes)))
    sign = "-" if minutes < 0 else ("+" if signed else "")
    h, m = divmod(total, 60)
    if h == 0:
        return f"{sign}{m} min"
    if m == 0:
        return f"{sign}{h} h"
    return f"{sign}{h} h {m:02d} min"


def _m(**kwargs) -> Metric:
    return Metric(**kwargs)


METRICS: dict[str, Metric] = {m.key: m for m in [
    # ---------------------------------------------------------------- forme
    _m(
        # « Readiness » était le seul mot anglais de l'interface, et un troisième
        # score d'état à côté de Forme et du badge du jour. Renommé en français
        # et rétrogradé au rang de point de comparaison externe : le verdict de
        # la page du jour vient de `tsb`, seul indicateur calculé ici.
        key="readiness_score", label="Disponibilité (Fitbit)", short="Disponibilité", unit="",
        family="forme", fmt="{:.0f}", direction=1, baseline="fixed", good_range=(65, 100),
        palette_index=5,
        what="Note sur 100 par laquelle Fitbit résume ton état de récupération du matin.",
        how_read="Combine la qualité du sommeil, la variabilité cardiaque et la FC de repos "
                 "de la nuit. Sous 65, l'appareil recommande une journée légère. Tant que la "
                 "montre est en période de calibration, la valeur n'est pas fiable (le "
                 "dashboard le signale ce jour-là).",
        provenance=PROV_FITBIT_SCORE,
    ),
    _m(
        key="tsb", label="Forme (TSB)", short="Forme", unit="",
        family="forme", fmt="{:+.1f}", direction=1, baseline="fixed", good_range=(-5, 15),
        palette_index=2,
        what="Fraîcheur du jour : ce qu'il te reste après avoir retiré la fatigue récente "
             "de la forme de fond.",
        how_read="TSB = CTL − ATL. Négatif, tu accumules plus de charge que tu n'en absorbes "
                 "(normal en progression, à ne pas prolonger) ; positif, tu es reposé et "
                 "c'est le bon moment pour une séance difficile. Le calcul demande 42 jours "
                 "d'historique pour être mûr : avant, la courbe est indicative.",
        provenance=PROV_COMPUTED,
    ),
    _m(
        key="ctl", label="Fond de forme (CTL)", short="Fond", unit="",
        family="forme", fmt="{:.1f}", direction=1, baseline="personal", palette_index=0,
        what="Charge d'entraînement absorbée en moyenne sur les 6 dernières semaines.",
        how_read="Moyenne exponentielle 42 jours de la charge cardio. Elle monte lentement "
                 "et redescend lentement : c'est le capital construit par l'entraînement "
                 "régulier, pas le résultat d'une seule séance.",
        provenance=PROV_COMPUTED,
    ),
    _m(
        key="atl", label="Fatigue (ATL)", short="Fatigue", unit="",
        family="forme", fmt="{:.1f}", direction=-1, baseline="personal", palette_index=1,
        what="Charge d'entraînement accumulée sur les 7 derniers jours.",
        how_read="Moyenne exponentielle 7 jours de la charge cardio. Elle réagit vite : "
                 "deux grosses séances la font grimper en quelques jours.",
        provenance=PROV_COMPUTED,
    ),
    _m(
        key="hrv_rmssd", label="Variabilité cardiaque (HRV)", short="HRV", unit=" ms",
        family="forme", fmt="{:.0f}", direction=1, baseline="personal", palette_index=6,
        what="Écart moyen entre deux battements consécutifs pendant la nuit (RMSSD).",
        how_read="Reflet de l'activité du système nerveux parasympathique. Une valeur haute "
                 "pour TOI signale un bon état de récupération ; il n'existe pas de norme "
                 "absolue, seule ta propre baseline compte. Baisse typiquement avec le "
                 "stress, l'alcool, le manque de sommeil ou une charge trop élevée.",
        provenance=PROV_FITBIT_DAILY,
    ),
    _m(
        key="resting_hr", label="Fréquence cardiaque au repos", short="FC repos", unit=" bpm",
        family="forme", fmt="{:.0f}", direction=-1, baseline="personal", palette_index=7,
        what="Fréquence cardiaque la plus basse observée au repos sur la journée.",
        how_read="Descend avec l'amélioration de la condition cardio, sur des semaines. "
                 "Une hausse de 3 à 5 bpm au-dessus de ta baseline pendant plusieurs jours "
                 "signale une fatigue, un manque de sommeil ou un début d'infection.",
        provenance=PROV_FITBIT_DAILY,
    ),
    _m(
        key="skin_temp_deviation_c", label="Écart de température cutanée", short="Δ Temp",
        unit=" °C", family="forme", fmt="{:+.2f}", direction=0, baseline="fixed",
        good_range=(-0.5, 0.5), palette_index=4,
        what="Écart de la température de peau nocturne par rapport à ta baseline sur 30 jours.",
        how_read="Un écart durable au-delà de ±0,5 °C accompagne souvent une infection, "
                 "un manque de sommeil ou une charge inhabituelle.",
        provenance=PROV_FITBIT_DAILY,
    ),
    _m(
        key="respiratory_rate", label="Fréquence respiratoire", short="Respiration",
        unit=" resp/min", family="forme", fmt="{:.1f}", direction=0, baseline="personal",
        palette_index=3,
        what="Nombre de respirations par minute pendant le sommeil.",
        how_read="Très stable d'une nuit à l'autre chez une même personne : c'est justement "
                 "pour ça qu'un écart de plus d'une respiration par minute mérite attention.",
        provenance=PROV_FITBIT_DAILY,
    ),

    # --------------------------------------------------------------- cardio
    _m(
        key="vo2_max", label="VO2max estimée", short="VO2max", unit=" ml/kg/min",
        family="cardio", fmt="{:.1f}", direction=1, baseline="personal", ma_window=14,
        palette_index=2,
        what="Estimation de ta consommation maximale d'oxygène : la meilleure mesure "
             "synthétique de la condition cardio-respiratoire.",
        how_read="C'est LA métrique de progression sur le long terme. Elle bouge lentement "
                 "(quelques dixièmes par mois) : ne juge jamais une variation quotidienne, "
                 "regarde la tendance sur plusieurs semaines. Estimation démographique "
                 "dérivée de la FC, pas une mesure en laboratoire.",
        provenance=PROV_FITBIT_DAILY,
    ),
    _m(
        # Un mot, un seul : « Charge » est la grandeur du JOUR. Ses deux
        # moyennes mobiles portent leurs propres noms — « Fond » (42 j) et
        # « Fatigue » (7 j) — et n'apparaissent que sur la courbe du même nom,
        # avec leur fenêtre en clair. Trois concepts, trois mots, trois
        # endroits.
        key="cardio_load_total", label="Charge cardio du jour", short="Charge", unit="",
        family="cardio", fmt="{:.0f}", direction=0, baseline="personal", palette_index=1,
        what="Somme de la contrainte cardiovasculaire de la journée, séances et vie "
             "quotidienne confondues.",
        how_read="À lire relativement à ton échelle personnelle (le minimum et le maximum "
                 "déjà observés sur ton historique), pas dans l'absolu. C'est cette série "
                 "qui alimente le modèle de forme CTL/ATL/TSB.",
        provenance=PROV_FITBIT_SCORE,
    ),
    _m(
        key="acwr_ratio", label="Ratio charge aiguë / chronique (ACWR)", short="ACWR", unit="",
        family="cardio", fmt="{:.2f}", direction=0, baseline="fixed", good_range=(0.8, 1.3),
        palette_index=3,
        what="Rapport entre la charge de la semaine écoulée et celle des dernières semaines.",
        how_read="Sous 0,8, tu t'entraînes moins que d'habitude (désentraînement). Au-dessus "
                 "de 1,3, l'augmentation est plus rapide que ce que le corps encaisse "
                 "habituellement, ce qui est associé à un risque de blessure accru. "
                 "Entre les deux : progression soutenable.",
        provenance=PROV_FITBIT_SCORE,
    ),
    _m(
        # « AZM » nu ne dit rien à personne : le sigle reste, entre parenthèses,
        # parce que c'est le nom que Fitbit affiche, mais il ne peut pas être le
        # libellé. Les noms de zone sont ceux de la carte « Temps en effort »
        # (Modérée / Soutenue / Pic) — un concept, un mot, partout le même.
        key="azm_points_total", label="Minutes actives (AZM)", short="Minutes actives (AZM)",
        unit=" pts", family="cardio", fmt="{:.0f}", direction=1, baseline="target",
        target=22, palette_index=1,
        what="Minutes d'activité comptées en POINTS, l'intensité valant double : 1 point "
             "par minute en zone modérée, 2 points par minute en zone soutenue ou pic.",
        how_read="Le barème explique qu'on puisse dépasser le nombre de minutes réellement "
                 "actives : 30 min de course intense font 60 points. La recommandation OMS "
                 "de 150 min d'activité modérée par semaine correspond à ~150 points, soit "
                 "environ 22 par jour.",
        provenance=PROV_FITBIT_DAILY,
    ),
    _m(
        key="hr_avg", label="Fréquence cardiaque moyenne", short="FC moy", unit=" bpm",
        family="cardio", fmt="{:.0f}", direction=0, baseline="personal", palette_index=7,
        what="Moyenne de tous les échantillons de FC de la journée (~37 000 mesures).",
        how_read="Mélange repos et effort : monte surtout avec le volume d'activité, pas "
                 "avec la condition physique. Peu utile seule, utile en tendance.",
        provenance=PROV_MEASURE,
    ),
    _m(
        key="spo2_avg", label="Saturation en oxygène", short="SpO2", unit=" %",
        family="cardio", fmt="{:.1f}", direction=1, baseline="fixed", good_range=(95, 100),
        palette_index=0,
        what="Pourcentage moyen d'oxygène dans le sang mesuré pendant le sommeil.",
        how_read="Normalement au-dessus de 95 %. Des valeurs basses et instables nuit après "
                 "nuit sont un signal à évoquer avec un médecin, pas à interpréter seul.",
        provenance=PROV_FITBIT_DAILY,
    ),

    # -------------------------------------------------------------- sommeil
    _m(
        key="sleep_minutes_asleep", label="Durée de sommeil", short="Sommeil", unit=" min",
        family="sommeil", fmt=FMT_DURATION, direction=1, baseline="target", target=480,
        palette_index=2,
        what="Temps réellement endormi sur la nuit principale (hors siestes).",
        how_read="À comparer à ton objectif Fitbit plutôt qu'aux 8 h génériques. Les siestes "
                 "sont comptées à part, pour ne pas masquer une nuit courte.",
        provenance=PROV_MEASURE,
    ),
    _m(
        key="sleep_score", label="Score de sommeil (Fitbit)", short="Score sommeil", unit="",
        family="sommeil", fmt="{:.0f}", direction=1, baseline="fixed", good_range=(75, 100),
        palette_index=2,
        what="Note sur 100 combinant durée, composition en stades et récupération.",
        how_read="Au-dessus de 75, la nuit est considérée comme bonne. Les trois sous-scores "
                 "(durée, composition, revitalisation) ne sont jamais renseignés dans cet "
                 "export : ils valent -2, c'est-à-dire « non calculé », et sont donc "
                 "délibérément vides ici plutôt qu'affichés à zéro.",
        provenance=PROV_FITBIT_SCORE,
    ),
    _m(
        key="sleep_efficiency_pct", label="Efficacité du sommeil", short="Efficacité",
        unit=" %", family="sommeil", fmt="{:.0f}", direction=1, baseline="fixed",
        good_range=(85, 100), palette_index=2,
        what="Part du temps passé au lit réellement passée à dormir.",
        how_read="Au-dessus de 85 % on parle d'un sommeil efficace. En dessous, le temps au "
                 "lit est long mais fragmenté : c'est un problème de qualité, pas de durée.",
        provenance=PROV_COMPUTED,
    ),
    _m(
        key="sleep_deep_minutes", label="Sommeil profond", short="Profond", unit=" min",
        family="sommeil", fmt=FMT_DURATION, direction=1, baseline="personal", palette_index=6,
        what="Minutes passées en sommeil lent profond.",
        how_read="Phase de récupération physique et de sécrétion d'hormone de croissance. "
                 "Représente typiquement 13 à 23 % de la nuit, surtout en première partie.",
        provenance=PROV_MEASURE,
    ),
    _m(
        key="sleep_rem_minutes", label="Sommeil paradoxal (REM)", short="REM", unit=" min",
        family="sommeil", fmt=FMT_DURATION, direction=1, baseline="personal", palette_index=4,
        what="Minutes passées en sommeil paradoxal.",
        how_read="Phase associée à la consolidation de la mémoire. Représente typiquement "
                 "20 à 25 % de la nuit, surtout en seconde partie : une nuit écourtée "
                 "ampute d'abord le REM.",
        provenance=PROV_MEASURE,
    ),
    _m(
        key="sleep_midpoint_minutes", label="Milieu de nuit", short="Milieu nuit",
        unit=" min", family="sommeil", fmt="{:.0f}", direction=0, baseline="personal",
        palette_index=4,
        what="Instant du milieu de la nuit, compté en minutes depuis 18 h.",
        how_read="Sert à mesurer la régularité des horaires, pas la qualité. L'ancrage à "
                 "18 h (et non à minuit) évite le saut de 1 440 minutes dès qu'un coucher "
                 "passe après 00 h — c'est ce saut qui rendait l'ancienne mesure de "
                 "régularité inexploitable. 360 = minuit, 540 = 3 h du matin.",
        provenance=PROV_COMPUTED,
    ),
    _m(
        key="sleep_debt", label="Dette de sommeil (14 j)", short="Dette", unit=" min",
        family="sommeil", fmt=FMT_DURATION_SIGNED, direction=-1, baseline="fixed", good_range=(-600, 0),
        palette_index=7,
        what="Cumul sur 14 jours de l'écart entre ton objectif de sommeil et ton sommeil réel.",
        how_read="Positif, tu as accumulé un déficit : une seule grasse matinée ne le "
                 "rattrape pas, c'est la régularité qui le résorbe.",
        provenance=PROV_COMPUTED,
    ),

    # ------------------------------------------------------------- activité
    _m(
        key="steps", label="Pas quotidiens", short="Pas", unit="",
        family="activite", fmt="{:,.0f}", direction=1, baseline="target", target=10000,
        palette_index=0,
        what="Nombre de pas de la journée, mesuré au poignet.",
        how_read="Une seule source est retenue par jour (la montre) : la montre et le "
                 "téléphone comptant tous les deux, les additionner gonflait artificiellement "
                 "le total.",
        provenance=PROV_MEASURE,
    ),
    _m(
        # « Kcal » ne correspondait pas à « Dépense » dans la navigation, et
        # l'unité est déjà portée par la valeur (« 2 145 kcal »).
        key="calories_total", label="Dépense énergétique", short="Dépense", unit=" kcal",
        family="activite", fmt="{:,.0f}", direction=0, baseline="target", palette_index=1,
        what="Dépense calorique totale estimée sur la journée, métabolisme de base compris.",
        how_read="À comparer à ton métabolisme de base (BMR) : l'écart est ce que l'activité "
                 "a réellement ajouté. Aucun apport alimentaire n'est disponible dans "
                 "l'export, donc aucun bilan énergétique n'est calculable.",
        provenance=PROV_FITBIT_DAILY,
    ),
    _m(
        key="kcal_zone_active", label="Calories en zone active", short="Kcal actives",
        unit=" kcal", family="activite", fmt="{:,.0f}", direction=1, baseline="personal",
        palette_index=1,
        what="Calories dépensées en zone modérée, vigoureuse ou pic.",
        how_read="Sépare la dépense de l'effort réel de celle du simple métabolisme. "
                 "C'est la part sur laquelle l'entraînement a prise.",
        provenance=PROV_FITBIT_DAILY,
    ),
    _m(
        key="sedentary_min", label="Temps sédentaire", short="Sédentarité", unit=" min",
        family="activite", fmt=FMT_DURATION, direction=-1, baseline="personal", palette_index=7,
        what="Minutes de la journée classées sans activité.",
        how_read="Le total compte moins que sa fragmentation : voir aussi la plus longue "
                 "période assise d'affilée, plus liée aux effets métaboliques.",
        provenance=PROV_FITBIT_DAILY,
    ),
    _m(
        key="longest_sedentary_period_min", label="Plus longue période assise",
        short="Assis d'affilée", unit=" min", family="activite", fmt=FMT_DURATION, direction=-1,
        baseline="fixed", good_range=(0, 90), palette_index=7,
        what="Durée du plus long bloc sédentaire ininterrompu de la journée.",
        how_read="Se lever quelques minutes toutes les heures limite les effets délétères "
                 "d'une position assise prolongée, indépendamment du total quotidien.",
        provenance=PROV_FITBIT_DAILY,
    ),
    _m(
        key="very_active_min", label="Minutes très actives", short="Très actif", unit=" min",
        family="activite", fmt=FMT_DURATION, direction=1, baseline="personal", palette_index=1,
        what="Minutes classées en activité intense.",
        how_read="Contrairement aux points AZM, ce sont bien des minutes réelles.",
        provenance=PROV_FITBIT_DAILY,
    ),
    _m(
        key="distance_m", label="Distance parcourue", short="Distance", unit=" m",
        family="activite", fmt="{:,.0f}", direction=1, baseline="personal", palette_index=0,
        what="Distance de la journée, dérivée des pas et de la longueur de foulée.",
        how_read="Comme pour les pas, une seule source par jour est retenue : la montre et "
                 "le téléphone se cumulaient auparavant.",
        provenance=PROV_MEASURE,
    ),

    # ---------------------------------------------------------------- renfo
    _m(
        key="total_work_minutes", label="Temps sous tension", short="Sous tension",
        unit=" min", family="renfo", fmt=FMT_DURATION, direction=1, baseline="personal",
        ma_window=4, palette_index=3,
        what="Somme des durées des séries de travail effectuées dans la semaine.",
        how_read="Une partie des durées est reconstruite : la source ne renseigne le début "
                 "de série que dans un tiers des cas, il est déduit de la fin du repos "
                 "précédent. Certaines séances n'ont aucun horodatage et n'apparaissent "
                 "donc qu'en nombre d'exécutions.",
        provenance=PROV_COMPUTED,
    ),
    _m(
        key="total_work_segments", label="Séries effectuées", short="Séries", unit="",
        family="renfo", fmt="{:.0f}", direction=1, baseline="personal", ma_window=4,
        palette_index=3,
        what="Nombre de séries de travail réalisées dans la semaine.",
        how_read="Unité complémentaire des minutes : un gainage de 45 s et une série de "
                 "squats ne se comparent pas en temps. C'est aussi la seule unité "
                 "disponible pour les séances sans horodatage.",
        provenance=PROV_COMPUTED,
    ),
    _m(
        key="strength_sessions_count", label="Séances de renforcement", short="Séances",
        unit="", family="renfo", fmt="{:.0f}", direction=1, baseline="target", target=3,
        ma_window=4, palette_index=3,
        what="Nombre de séances guidées de renforcement dans la semaine.",
        how_read="Objectif de référence : 2 à 3 séances hebdomadaires par groupe musculaire "
                 "pour progresser en force.",
        provenance=PROV_MEASURE,
    ),
    _m(
        key="avg_rpe", label="Effort perçu (RPE)", short="RPE", unit="/10",
        family="renfo", fmt="{:.1f}", direction=0, baseline="fixed", good_range=(6, 8),
        ma_window=3, palette_index=3,
        what="Difficulté ressentie de la séance, déclarée par toi de 1 à 10.",
        how_read="Seule métrique subjective du dashboard, et la seule qui capte ce que les "
                 "capteurs ne voient pas. Entre 6 et 8, la séance est assez dure pour "
                 "provoquer une adaptation sans compromettre la récupération.",
        provenance=PROV_MEASURE,
    ),

    # ------------------------------------------------------ qualité données
    _m(
        key="data_completeness", label="Complétude des données", short="Complétude",
        unit=" %", family="qualite", fmt="{:.0%}", direction=1, baseline="fixed",
        good_range=(0.8, 1.2), palette_index=5,
        what="Part de la journée réellement couverte par la montre, mesurée en nombre "
             "d'échantillons de fréquence cardiaque rapporté à une journée pleine.",
        how_read="Sous 80 %, la journée est marquée partielle et exclue des moyennes : "
                 "le premier jour de port et le jour de l'export sont incomplets par "
                 "nature et fausseraient les bords de chaque série.",
        provenance=PROV_COMPUTED,
    ),
]}


#: Les seules métriques dont un RETARD est en soi un signal, et donc les seules
#: qui aient le droit de porter de la couleur dans une tuile.
#:
#: La distinction est physiologique, pas graphique. Une charge à −21 ou une
#: dépense à −782 un jour de repos ne sont pas de mauvaises nouvelles : ce sont
#: des faits, et les peindre en rouge invente un jugement que la donnée ne porte
#: pas. Une variabilité cardiaque en baisse ou une fréquence de repos en hausse,
#: en revanche, disent quelque chose du système nerveux autonome quel qu'ait été
#: le programme de la journée.
#:
#: Deux clés, donc deux points colorés au maximum sur la grille — et seulement
#: quand l'écart va dans le mauvais sens.
SIGNAL_KEYS: frozenset[str] = frozenset({"hrv_rmssd", "resting_hr"})


# Métriques proposées par défaut dans l'explorateur : celles qui ont un sens
# quotidien et une variance exploitable sur un historique court.
EXPLORER_DEFAULT: tuple[str, ...] = (
    "steps", "calories_total", "sleep_minutes_asleep", "resting_hr",
    "hrv_rmssd", "readiness_score", "cardio_load_total", "sedentary_min",
)


def get(key: str) -> Metric | None:
    return METRICS.get(key)


def require(key: str) -> Metric:
    metric = METRICS.get(key)
    if metric is None:
        raise KeyError(f"Métrique inconnue : {key!r}. Ajoute-la dans health/metrics.py.")
    return metric


def by_family(family: str) -> list[Metric]:
    return [m for m in METRICS.values() if m.family == family]


def families() -> list[tuple[str, str, list[Metric]]]:
    """(clé, libellé, métriques) pour chaque famille, dans l'ordre d'affichage."""
    return [(key, label, by_family(key)) for key, label in FAMILIES.items()]


def keys_in(columns) -> list[str]:
    """Métriques du registre effectivement présentes dans un DataFrame."""
    available = set(columns)
    return [k for k in METRICS if k in available]

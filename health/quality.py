"""Ce en quoi on a le droit d'avoir confiance.

Une seule question, posée à un seul endroit : **cette journée a-t-elle été
suffisamment mesurée pour compter ?** Elle se posait jusqu'ici trois fois, dans
trois fichiers, avec trois réponses différentes — et le plus souvent elle ne se
posait pas du tout.

`mart.daily` marque chaque journée de deux drapeaux (cf. health/sql/200_daily.sql) :

    is_missing_day   aucun échantillon de fréquence cardiaque
    is_partial_day   moins de 80 % d'une journée pleine d'échantillons

Ces drapeaux ne suffisent pas : ce qui compte est ce qu'on en FAIT, et les deux
usages sont opposés.

* Pour une **normale personnelle**, une journée mal couverte doit sortir. Elle
  sous-compte tout ce qui s'additionne (pas, dépense, minutes d'effort), et
  l'inclure tire la référence vers le bas — au point de faire passer une
  journée ordinaire pour une bonne journée.

* Pour un **modèle de charge** (CTL/ATL), elle ne peut PAS sortir : une moyenne
  exponentielle a une cadence quotidienne, retirer un jour du milieu décalerait
  toute la décroissance. Mais la laisser telle quelle est pire encore, car le
  modèle lit alors une charge sous-enregistrée comme une journée facile — une
  journée à 66 % de couverture et 15,2 de charge se lit exactement comme une
  vraie journée calme, et gonfle d'autant la fraîcheur du lendemain.

D'où deux fonctions et non une : `reference_frame` retire, `impute_partial_load`
remplace.
"""
from __future__ import annotations

import pandas as pd

#: Colonnes de qualité de `mart.daily`. Une journée est retenue si AUCUNE n'est
#: vraie ; une colonne absente du DataFrame est simplement ignorée, ce qui rend
#: ces fonctions utilisables sur des tables dérivées qui ne les portent pas.
QUALITY_FLAGS = ("is_partial_day", "is_missing_day")

#: Fenêtre de la médiane qui remplace la charge d'une journée mal couverte.
#: La même que la fenêtre de normalité employée partout ailleurs : la charge
#: imputée est « une journée comme les autres, récemment ».
IMPUTE_WINDOW_DAYS = 28

#: Il faut au moins ce nombre de journées mesurées dans la fenêtre pour que la
#: médiane veuille dire quelque chose. En deçà, mieux vaut la charge
#: sous-enregistrée — au moins elle a été mesurée.
IMPUTE_MIN_DAYS = 5


def is_measured(df: pd.DataFrame, flags: tuple[str, ...] = QUALITY_FLAGS) -> pd.Series:
    """Masque booléen : `True` pour les journées suffisamment couvertes.

    Un DataFrame sans aucune colonne de qualité renvoie `True` partout — c'est
    le comportement correct pour une table dérivée qui a déjà fait le tri, et
    non un silence sur un problème.
    """
    present = [c for c in flags if c in df.columns]
    if not present:
        return pd.Series(True, index=df.index)
    return ~df[present].fillna(False).astype(bool).any(axis=1)


def count_measured(df: pd.DataFrame, flags: tuple[str, ...] = QUALITY_FLAGS) -> int:
    """Nombre de journées réellement mesurées.

    Ce que `len(df)` ne dit pas : il compte les lignes du calendrier, jours sans
    montre compris. « 39 jours d'historique » quand deux d'entre eux n'ont
    presque rien enregistré annonce une profondeur de données qui n'existe pas.
    """
    return int(is_measured(df, flags).sum())


def reference_frame(
    df: pd.DataFrame, keep=None, date_col: str = "local_date",
    flags: tuple[str, ...] = QUALITY_FLAGS,
) -> pd.DataFrame:
    """Historique réduit aux journées qui ont le droit de DÉFINIR une normale.

    `keep` (une date) est conservée même mal couverte. C'est la journée qu'on
    est en train de juger : elle doit rester la dernière ligne du cadre pour
    que les `.iloc[-1]` des appelants visent bien ce jour-là, et l'interface
    avertit déjà par ailleurs de ce que vaut sa mesure. Ce qu'on lui refuse,
    c'est de définir la normale des autres — pas d'être regardée.
    """
    measured = is_measured(df, flags)
    if keep is not None and date_col in df.columns:
        measured = measured | (pd.to_datetime(df[date_col]).dt.date == keep)
    return df.loc[measured]


def impute_partial_load(
    df: pd.DataFrame, load_col: str = "cardio_load_total",
    date_col: str = "local_date", window_days: int = IMPUTE_WINDOW_DAYS,
    flags: tuple[str, ...] = QUALITY_FLAGS,
) -> pd.DataFrame:
    """Copie de `df` où la charge des journées mal couvertes est remplacée par
    la médiane glissante des journées mesurées qui les précèdent.

    Ajoute une colonne booléenne `load_imputed` : sans elle, l'interface ne
    pourrait pas dire au lecteur que le verdict repose en partie sur une valeur
    reconstruite, et une reconstruction silencieuse est indiscernable d'une
    mesure.

    **Médiane et non division par la couverture.** Diviser paraît plus direct
    — 15,2 de charge sur 66 % de journée ferait 23 — mais suppose la charge
    répartie uniformément dans la journée, alors qu'une séance y est
    concentrée : selon que la montre a manqué la séance ou la nuit, le même
    calcul sous-estime ou invente. À 26 % de couverture il multiplie en outre
    une mesure déjà bruitée par 3,8. La médiane, elle, est bornée et dit
    exactement ce qu'elle prétend : « une journée ordinaire, faute de mieux ».

    Une journée mesurée n'est JAMAIS modifiée, et la médiane ne regarde que le
    passé (`closed="left"`) : la charge d'un jour ne peut pas être reconstruite
    à partir de jours qui n'avaient pas encore eu lieu.
    """
    out = df.copy()
    if load_col not in out.columns or date_col not in out.columns:
        out["load_imputed"] = False
        return out

    out = out.sort_values(date_col)
    bad = ~is_measured(out, flags)
    out["load_imputed"] = False
    if not bad.any():
        return out

    # Médiane des seules journées MESURÉES : imputer depuis une fenêtre qui
    # contient d'autres journées partielles propagerait leur sous-comptage.
    measured_load = out[load_col].where(~bad)
    window = pd.DataFrame({date_col: pd.to_datetime(out[date_col]), "v": measured_load.to_numpy()})
    median = (
        window.rolling(f"{window_days}D", on=date_col, min_periods=IMPUTE_MIN_DAYS, closed="left")["v"]
        .median()
        .to_numpy()
    )
    median = pd.Series(median, index=out.index)

    replace = bad & median.notna()
    out.loc[replace, load_col] = median[replace]
    out.loc[replace, "load_imputed"] = True
    return out

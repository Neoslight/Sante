"""Tests des parties calculatoires / échappement HTML de app/ui.py.

Ne dépend pas d'une vraie session Streamlit : les widgets (`st.columns`,
`st.button`, `st.markdown`...) fonctionnent en mode "bare" (hors `streamlit
run`) sans lever -- ils se contentent d'un avertissement et de valeurs par
défaut (`st.button` renvoie toujours `False`). On capture les appels à
`st.markdown` par monkeypatch pour vérifier le HTML produit sans avoir besoin
d'un vrai navigateur ni d'un ScriptRunContext.

`app/` n'est pas un package (pas de __init__.py, imports "plats" comme dans
les pages Streamlit) : on ajoute son dossier à sys.path, comme le fait
tests/test_charts.py.
"""
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

import ui  # noqa: E402


# --- stabilité de _notice_id -------------------------------------------------
def test_notice_id_is_stable_for_same_text_and_kind():
    assert ui._notice_id("Texte identique", "warning") == ui._notice_id("Texte identique", "warning")


def test_notice_id_changes_when_text_changes():
    id_a = ui._notice_id("Premier texte", "warning")
    id_b = ui._notice_id("Second texte", "warning")
    assert id_a != id_b


def test_notice_id_changes_when_kind_changes():
    """Un même libellé utilisé une fois en info et une fois en warning ne doit
    pas partager son état masqué -- cf. docstring de `ui.notice`."""
    id_info = ui._notice_id("Même texte", "info")
    id_warning = ui._notice_id("Même texte", "warning")
    assert id_info != id_warning


def test_notice_id_is_a_short_hex_string():
    msg_id = ui._notice_id("Texte", "info")
    assert len(msg_id) == 12
    int(msg_id, 16)  # lève ValueError si ce n'est pas de l'hexadécimal


# --- échappement HTML ---------------------------------------------------
def _capture_markdown(monkeypatch, module):
    """Remplace `st.markdown` par un espion qui garde le dernier HTML rendu,
    sans dépendre d'une session Streamlit réelle."""
    calls: list[str] = []
    monkeypatch.setattr(module.st, "markdown", lambda html, **kw: calls.append(html))
    return calls


def test_empty_state_escapes_html_in_text_and_hint(monkeypatch):
    calls = _capture_markdown(monkeypatch, ui)
    ui.empty_state("<script>alert(1)</script>", hint="<b>indice</b>")
    assert len(calls) == 1
    assert "<script>" not in calls[0]
    assert "&lt;script&gt;" in calls[0]
    assert "&lt;b&gt;indice&lt;/b&gt;" in calls[0]


def test_empty_state_without_hint_omits_hint_block():
    # Pas de monkeypatch ici : st.markdown fonctionne en mode bare (warning,
    # pas d'exception) -- on vérifie juste l'absence de levée.
    ui.empty_state("Rien à signaler ici")


def test_notice_escapes_html_in_text(monkeypatch):
    monkeypatch.setattr(st, "session_state", {})
    calls = _capture_markdown(monkeypatch, ui)
    ui.notice("<img src=x onerror=alert(1)>", kind="warning", msg_id="test-xss")
    assert calls, "st.markdown aurait dû être appelé (message non masqué)"
    rendered = calls[0]
    assert "<img" not in rendered
    assert "&lt;img" in rendered


def test_notice_dismissed_message_renders_nothing(monkeypatch):
    monkeypatch.setattr(st, "session_state", {"dismissed_notices": {"already-dismissed"}})
    calls = _capture_markdown(monkeypatch, ui)
    ui.notice("Texte quelconque", kind="info", msg_id="already-dismissed")
    assert calls == []


def test_card_escapes_html_in_title_and_caption(monkeypatch):
    calls = _capture_markdown(monkeypatch, ui)
    with ui.card("<b>Titre</b>", caption="<i>Légende</i>"):
        pass
    assert len(calls) == 1
    assert "<b>Titre</b>" not in calls[0]
    assert "&lt;b&gt;Titre&lt;/b&gt;" in calls[0]
    assert "&lt;i&gt;Légende&lt;/i&gt;" in calls[0]


# --- bande de jours : la frontière de mois -----------------------------------
def _strip_html(monkeypatch, days, selected) -> list[str]:
    captured: list[str] = []
    monkeypatch.setattr(ui.st, "markdown", lambda html, **kw: captured.append(html))
    ui.day_strip(days, [str(d.day) for d in days], [None] * len(days), selected)
    return captured


def test_day_strip_marks_where_the_month_changes(monkeypatch):
    """La date en toutes lettres au-dessus de la bande ne suffit que tant que
    la bande reste dans un mois. Le 3 août, elle affiche « 21 … 31 1 2 3 » sous
    un titre qui ne dit qu'« août », et rien ne signale que la moitié gauche est
    de juillet."""
    import datetime as dt
    days = [dt.date(2026, 7, 30) + dt.timedelta(days=i) for i in range(5)]
    html = "".join(_strip_html(monkeypatch, days, days[-1]))
    assert "st-key-daystrip-2026-08-01" in html and "border-left" in html
    # Un seul repère, celui du 1er août — pas un par jour du mois suivant.
    assert html.count("border-left") == 1


def test_day_strip_stays_bare_inside_a_single_month(monkeypatch):
    """Un repère qui ne repère rien est du bruit : sans frontière, aucun filet."""
    import datetime as dt
    days = [dt.date(2026, 7, 12) + dt.timedelta(days=i) for i in range(5)]
    html = "".join(_strip_html(monkeypatch, days, days[-1]))
    assert "border-left" not in html


def test_day_strip_never_marks_the_first_day_of_the_strip(monkeypatch):
    """Le premier jour n'a pas de voisin de gauche : un filet y serait un bord."""
    import datetime as dt
    days = [dt.date(2026, 8, 1) + dt.timedelta(days=i) for i in range(4)]
    html = "".join(_strip_html(monkeypatch, days, days[0]))
    assert "border-left" not in html

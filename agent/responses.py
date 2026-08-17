"""Phrasenbank: die in Abschnitt 14-47 der Spezifikation woertlich vorgegebenen
Formulierungen. Sicherheits- und geschaeftskritische Aussagen werden hier
deterministisch erzeugt (nicht vom LLM), damit sie garantiert korrekt sind.

Jede Methode, die eine Wahrheitsbehauptung enthaelt (Online-Auftritt, Entwurf,
Versand, Termin), nutzt agent/guardrails.py um die Behauptung abzusichern.
"""

from __future__ import annotations

from agent.context import LeadData
from agent.guardrails import (
    can_claim_entwurf_vorhanden,
    can_claim_online_auftritt_geprueft,
)
from core.config import BusinessConfig


class ResponseBank:
    def __init__(self, agent_name: str, company_name: str, company_location: str, biz: BusinessConfig):
        self.agent_name = agent_name
        self.company_name = company_name
        self.company_location = company_location
        self.biz = biz

    # --- Begruessung / Gatekeeper (Abschnitt 14) ---

    def greeting(self, lead: LeadData) -> str:
        # Feste, woertlich vorgegebene Begruessung (nicht mehr lead-spezifisch
        # wie zuvor - die Pruefung, ob die richtige Ansprechperson am Telefon
        # ist, passiert jetzt separat ueber gatekeeper_ask_responsible(),
        # sobald sich das im Gespraech als noetig erweist). `lead` bleibt
        # Teil der Signatur fuer Konsistenz mit den uebrigen ResponseBank-
        # Methoden und moegliche kuenftige Personalisierung.
        del lead
        return (
            f"Guten Tag! Hier ist {self.agent_name}, der digitale Assistent von "
            f"{self.company_name} aus {self.company_location}. Haben Sie gerade "
            "einen Moment Zeit?"
        )

    def gatekeeper_ask_responsible(self) -> str:
        return "Ich haette eine kurze Frage zu Ihrer Webseite. Wer ist bei Ihnen dafuer zustaendig?"

    def gatekeeper_explain_topic(self, lead: LeadData) -> str:
        if can_claim_entwurf_vorhanden(lead):
            return (
                "Wir haben fuer Ihr Unternehmen bereits einen unverbindlichen "
                "Webseiten-Entwurf vorbereitet und wuerden ihn der zustaendigen Person "
                "gerne kurz zeigen."
            )
        return (
            "Wir haetten einen konkreten Vorschlag fuer Ihren Online-Auftritt und wuerden "
            "diesen gerne kurz mit der zustaendigen Person besprechen."
        )

    # --- Person nicht da (Abschnitt 15) ---

    def person_not_available(self) -> str:
        return "Kein Problem. Wann kann ich sie am besten erreichen?"

    # --- Nachricht ausrichten (Abschnitt 16) ---

    def message_relay(self, lead: LeadData) -> str:
        if can_claim_entwurf_vorhanden(lead):
            return (
                f"Sehr gerne. Bitte richten Sie aus, dass {self.company_name} aus "
                f"{self.company_location} wegen eines unverbindlichen Webseiten-Entwurfs "
                f"angerufen hat."
            )
        return (
            f"Sehr gerne. Bitte richten Sie aus, dass {self.company_name} aus "
            f"{self.company_location} bezueglich des Online-Auftritts angerufen hat."
        )

    def thanks_for_help(self) -> str:
        return "Vielen Dank fuer Ihre Hilfe."

    # --- Zustaendige Person dran (Abschnitt 17) ---

    def website_check_intro(self, lead: LeadData) -> str:
        if can_claim_online_auftritt_geprueft(lead):
            return "Wir haben uns Ihren Online-Auftritt angesehen und dabei gesehen, dass noch Potenzial vorhanden ist."
        return "Wir beschaeftigen uns viel mit Online-Auftritten von Unternehmen wie Ihrem."

    def ask_current_website_satisfaction(self) -> str:
        return "Darf ich kurz fragen: Haben Sie bereits eine Webseite und sind Sie damit zufrieden?"

    # --- Keine Webseite (Abschnitt 18) ---

    def no_website_pitch(self) -> str:
        return (
            "Verstehe. Viele potenzielle Kunden suchen zuerst ueber Google. Eine eigene "
            "Webseite kann Leistungen, Bilder, Kontaktdaten und Oeffnungszeiten uebersichtlich "
            "an einem Ort zeigen."
        )

    def offer_design_no_website(self, lead: LeadData) -> str | None:
        if not can_claim_entwurf_vorhanden(lead):
            return None
        return (
            "Genau dafuer haben wir bereits einen unverbindlichen Entwurf vorbereitet. So "
            "koennen Sie direkt sehen, wie eine Webseite fuer Ihr Unternehmen aussehen "
            "koennte. Darf ich Ihnen den einmal zuschicken?"
        )

    # --- Webseite vorhanden (Abschnitt 19) ---

    def existing_website_note(self) -> str:
        return "Verstehe. Gerade auf dem Handy sollte eine Webseite modern, uebersichtlich und professionell wirken."

    def offer_design_existing_website(self, lead: LeadData) -> str | None:
        if not can_claim_entwurf_vorhanden(lead):
            return None
        return (
            "Wir haben dazu bereits einen unverbindlichen Entwurf vorbereitet. So koennen "
            "Sie direkt sehen, wie eine modernere Variante Ihres Online-Auftritts aussehen "
            "koennte. Darf ich Ihnen den einmal zuschicken?"
        )

    # --- Kunde zufrieden (Abschnitt 20) ---

    def customer_satisfied_ack(self) -> str:
        return "Das ist natuerlich gut."

    def offer_design_as_comparison(self, lead: LeadData) -> str | None:
        if not can_claim_entwurf_vorhanden(lead):
            return None
        return (
            "Da wir bereits einen unverbindlichen Entwurf vorbereitet haben, koennten Sie "
            "ihn sich trotzdem einmal als zusaetzlichen Vergleich ansehen. Darf ich ihn "
            "Ihnen zuschicken?"
        )

    # --- Zwei-Nein-Regel Ende (Abschnitt 21/22) ---

    def polite_end_after_rejection(self) -> str:
        return "Alles klar, gar kein Problem. Vielen Dank fuer Ihre Zeit."

    def first_rejection_ack(self) -> str:
        return "Verstehe."

    def offer_design_despite_rejection(self, lead: LeadData) -> str | None:
        if not can_claim_entwurf_vorhanden(lead):
            return None
        return (
            "Da wir fuer Ihr Unternehmen bereits einen unverbindlichen Entwurf vorbereitet "
            "haben: Darf ich Ihnen den trotzdem einmal zusenden? Sie koennen ihn sich "
            "einfach in Ruhe anschauen."
        )

    # --- "Wir haben schon jemanden" (Abschnitt 23) ---

    def already_have_provider_ack(self) -> str:
        return "Verstehe, das ist natuerlich kein Problem."

    # --- "Wir brauchen keine Webseite" (Abschnitt 24) ---

    def ask_social_media_or_alternative(self) -> str:
        return "Nutzen Sie aktuell hauptsaechlich Social Media oder haben Sie bereits eine andere Loesung?"

    # --- "Keine Zeit" (Abschnitt 25) ---

    def no_time_ack(self) -> str:
        return "Kein Problem."

    def ask_callback_time(self) -> str:
        return "Wann darf ich Sie kurz noch einmal anrufen?"

    def ask_send_design_when_time(self) -> str:
        return (
            "Darf ich Ihnen den Entwurf einfach per E-Mail oder WhatsApp zusenden? Dann "
            "koennen Sie ihn sich ansehen, wenn Sie Zeit haben."
        )

    # --- Wait Mode (Abschnitt 26) ---

    def wait_ack(self) -> str:
        return "Kein Problem. Ich warte."

    def wait_ack_alt(self) -> str:
        return "Natuerlich, kein Problem. Ich warte."

    def still_there(self) -> str:
        return "Sind Sie noch da?"

    # --- Preise (Abschnitt 31-34) ---

    def pricing_website(self) -> str:
        amount = self.biz.pricing.get("website_monthly_from", 300)
        return f"Webseiten beginnen bei {amount} Euro monatlich. Der genaue Preis haengt vom Umfang und den gewuenschten Funktionen ab."

    def pricing_maintenance(self) -> str:
        amount = self.biz.pricing.get("maintenance_monthly_from", 100)
        return (
            "Nach vollstaendiger Bezahlung bleibt nur noch die laufende Betreuung fuer "
            f"Hosting, Pflege und Support. Diese beginnt bei {amount} Euro monatlich."
        )

    def pricing_details_fallback(self) -> str:
        return "Die genauen Konditionen haengen vom Projekt ab. Unsere Geschaeftsleitung erstellt Ihnen dafuer ein transparentes Angebot."

    def no_budget_response(self) -> str:
        return "Das verstehe ich. Wir bieten auch flexible Zahlungsmodelle an."

    def pricing_seo(self) -> str:
        amount = self.biz.pricing.get("seo_monthly_from", 200)
        return f"SEO Growth beginnt bei {amount} Euro monatlich. Welche Massnahmen sinnvoll sind, haengt von Ihrer Webseite und Ihren Zielen ab."

    def pricing_admin_systems(self) -> str:
        return "Verwaltungssysteme werden individuell geplant und auf Anfrage kalkuliert."

    # --- Deutschlandweit (Abschnitt 35) ---

    def nationwide(self) -> str:
        return f"Das ist kein Problem. {self.company_name} arbeitet deutschlandweit und wir koennen alles bequem online besprechen."

    def video_call_offer(self) -> str:
        return "Dafuer koennen wir einen kurzen Videocall vereinbaren. Den Link erhalten Sie per E-Mail oder WhatsApp."

    # --- Entwurf zusenden (Abschnitt 36) ---

    def ask_contact_channel(self) -> str:
        return "Sehr gerne. Was waere Ihnen lieber: per E-Mail oder per WhatsApp?"

    def confirm_email_repeat(self, email: str) -> str:
        return f"Ich wiederhole zur Kontrolle: {email}. Ist das so richtig?"

    def confirm_phone_repeat(self, phone: str) -> str:
        return f"Ich wiederhole zur Kontrolle: {phone}. Ist das so richtig?"

    def design_sent_confirmation(self) -> str:
        return "Ich habe den Entwurf soeben an Sie versendet."

    def design_send_pending(self) -> str:
        return "Ich habe die Adresse aufgenommen und gebe das entsprechend weiter."

    # --- Wer meldet sich (Abschnitt 44) ---

    def who_will_contact(self) -> str:
        return "Unsere Geschaeftsleitung wird sich persoenlich bei Ihnen melden und alles Weitere mit Ihnen besprechen."

    # --- Termin ohne Kalender (Abschnitt 43) ---

    def callback_without_calendar(self) -> str:
        return "Ich gebe Ihren Terminwunsch an unsere Geschaeftsleitung weiter. Sie erhalten anschliessend eine Bestaetigung."

    def ask_general_availability(self) -> str:
        return "Sehr gerne. Wann wuerde es Ihnen grundsaetzlich gut passen?"

    # --- Erfolgreicher Abschluss (Abschnitt 71) ---

    def success_closing(self, design_actually_sent: bool) -> str:
        if design_actually_sent:
            versand = "Sie erhalten den Entwurf in Kuerze per E-Mail."
        else:
            versand = "Wir geben Ihre Daten entsprechend weiter."
        return (
            f"Alles klar. {versand} Schauen Sie ihn sich gerne in Ruhe an. Wenn Ihnen der "
            "Entwurf gefaellt, gebe ich alles direkt an unsere Geschaeftsleitung weiter. Sie "
            "wird sich persoenlich bei Ihnen melden und Ihre Wuensche mit Ihnen besprechen. "
            "Vielen Dank fuer Ihre Zeit und auf Wiederhoeren."
        )

    # --- Verabschiedung (Abschnitt 46/47) ---

    def farewell_reply(self) -> str:
        return "Vielen Dank. Auf Wiederhoeren."

    def farewell_reply_simple(self) -> str:
        return "Auf Wiederhoeren."

    def friendly_wish_reply(self) -> str:
        return "Vielen Dank, das wuensche ich Ihnen auch. Einen schoenen Tag noch und auf Wiederhoeren."

    # --- Identitaet (Abschnitt 8) ---

    def identity_disclosure(self) -> str:
        return f"Ich bin die digitale Assistenz von {self.company_name}."

    # --- Do-Not-Call (Abschnitt 45) ---

    def do_not_call_ack(self) -> str:
        return "Natuerlich. Entschuldigen Sie die Stoerung."

    # --- Uebergabe an Geschaeftsleitung (Abschnitt 43) ---

    def handoff_note(self) -> str:
        return (
            "Wenn Ihnen der Entwurf gefaellt, gebe ich alles direkt an unsere "
            "Geschaeftsleitung weiter. Sie wird sich persoenlich bei Ihnen melden und Ihre "
            "Wuensche mit Ihnen besprechen."
        )

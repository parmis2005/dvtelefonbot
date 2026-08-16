"""Hilfsfunktionen zur Erzeugung von PJSIP/ARI-Konfigurationsschnipseln fuer
Asterisk. Wird von scripts/setup_mac.sh referenziert und kann zur
Dokumentation/als Ausgangspunkt fuer die echte Asterisk-Konfiguration
(pjsip.conf, extensions.conf, ari.conf) genutzt werden.

Diese Datei erzeugt Text - sie fasst KEINE laufende Asterisk-Instanz an.
"""

from __future__ import annotations


def render_ari_conf(username: str, password: str) -> str:
    return (
        "[general]\n"
        "enabled = yes\n"
        "pretty = yes\n\n"
        f"[{username}]\n"
        "type = user\n"
        f"password = {password}\n"
        "read_only = no\n"
    )


def render_pjsip_trunk_conf(
    trunk_name: str,
    sip_server: str,
    sip_username: str,
    sip_password: str,
) -> str:
    return f"""[{trunk_name}]
type = registration
transport = transport-udp
outbound_auth = {trunk_name}-auth
server_uri = sip:{sip_server}
client_uri = sip:{sip_username}@{sip_server}
retry_interval = 60

[{trunk_name}-auth]
type = auth
auth_type = userpass
username = {sip_username}
password = {sip_password}

[{trunk_name}]
type = aor
contact = sip:{sip_server}

[{trunk_name}]
type = endpoint
transport = transport-udp
context = dario-outbound
disallow = all
allow = ulaw,alaw,g722
outbound_auth = {trunk_name}-auth
aors = {trunk_name}

[{trunk_name}]
type = identify
endpoint = {trunk_name}
match = {sip_server}
"""


def render_extensions_conf(app_name: str, context: str = "dario-outbound") -> str:
    return f"""[{context}]
exten => _X.,1,NoOp(Dario Outbound Call)
 same => n,Stasis({app_name})
 same => n,Hangup()

[dario-inbound]
exten => _X.,1,NoOp(Dario Inbound Call)
 same => n,Answer()
 same => n,Stasis({app_name})
 same => n,Hangup()
"""

from app.chat_parser import parse_chat_text

IOS = """\u200e[23/11/2026 14:32:10] Ana: Oi, tudo bem?
[23/11/2026 14:33:01] Bruno: \u200e<anexado: 00000012-AUDIO-2026-11-23-14-33-01.opus>
[23/11/2026 14:35:00] Ana: mensagem
com varias linhas
\u200e[23/11/2026 14:36:00] Ana: \u200e<anexado: 00000013-PTT-2026-11-23-14-36-00.opus>
"""

ANDROID = """23/11/2026 14:32 - As mensagens sao criptografadas
23/11/2026 14:33 - Bruno: PTT-20261123-WA0001.opus (arquivo anexado)
23/11/2026 14:34 - Ana: ola
"""

US = """11/23/26, 2:33 PM - Bruno: PTT-20261123-WA0001.opus (file attached)
11/24/26, 2:33 AM - Ana: hi
"""


def test_ios_audio_and_multiline():
    a = {"00000012-AUDIO-2026-11-23-14-33-01.opus": "x/a.opus",
         "00000013-PTT-2026-11-23-14-36-00.opus": "x/b.opus"}
    msgs = parse_chat_text(IOS, a)
    assert [m.sender for m in msgs] == ["Ana", "Bruno", "Ana", "Ana"]
    assert msgs[1].audio_path == "x/a.opus"
    assert msgs[3].audio_path == "x/b.opus"
    assert msgs[2].text == "mensagem\ncom varias linhas"
    assert msgs[0].timestamp == "2026-11-23T14:32:10"


def test_android_and_system_message():
    msgs = parse_chat_text(ANDROID, {"PTT-20261123-WA0001.opus": "PTT-20261123-WA0001.opus"})
    assert msgs[0].sender is None
    assert msgs[1].audio_name == "PTT-20261123-WA0001.opus"
    assert msgs[1].sender == "Bruno"


def test_us_format_month_first_and_ampm():
    msgs = parse_chat_text(US, {"PTT-20261123-WA0001.opus": "p"})
    assert msgs[0].timestamp == "2026-11-23T14:33:00"
    assert msgs[1].timestamp == "2026-11-24T02:33:00"


def test_orphan_audio_is_appended():
    msgs = parse_chat_text("23/11/2026 14:34 - Ana: ola\n", {"solto.opus": "solto.opus"})
    assert msgs[-1].audio_orphan and msgs[-1].audio_name == "solto.opus"

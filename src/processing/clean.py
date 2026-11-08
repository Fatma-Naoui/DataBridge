import re
import unicodedata

import ftfy

QUOTED = re.compile(
    r"(?im)^(on .{10,120} wrote:|le .{10,120} a écrit\s?:|op .{10,120} schreef.*:"
    r"|-{2,}\s*(original message|message d.origine|oorspronkelijk bericht)\s*-{2,})\s*$"
)
DISCLAIMER = re.compile(
    r"(?im)^.*(this (e-?mail|message)[^\n]{0,80}confidential"
    r"|dit (e-?mail)?bericht[^\n]{0,80}vertrouwelijk"
    r"|ce (message|courriel)[^\n]{0,80}confidentiel"
    r"|avant d.imprimer|please consider the environment).*$"
)
MOBILE_SIG = re.compile(
    r"(?im)^\s*(verstuurd (vanuit|van mijn)|envoyé (de mon|depuis)|sent from).*$"
)
SIGNOFF = re.compile(
    r"(?im)^\s*(met vriendelijke groeten?|vriendelijke groeten?|mvg|cordialement"
    r"|bien cordialement|bien à vous|salutations[^\n]*|best regards|kind regards"
    r"|regards|sincerely|alvast bedankt|bedankt voor de snelle hulp"
    r"|merci d.avance|thanks in advance)\s*[!.,]?\s*$"
)
REMINDER_PREFIX = re.compile(r"(?i)rappel\s*/\s*reminder\s*/\s*herinnering\s*:\s*")
REPLY_PREFIX = re.compile(r"(?im)^(re|tr|fw|aw)\s*:\s*")


def clean(text: str) -> str:
    text = unicodedata.normalize("NFC", ftfy.fix_text(text or ""))
    text = REMINDER_PREFIX.sub("", text)
    text = REPLY_PREFIX.sub("", text)
    if m := QUOTED.search(text):
        text = text[: m.start()]
    text = "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith(">")
    )
    if m := DISCLAIMER.search(text):
        text = text[: m.start()]
    if m := MOBILE_SIG.search(text):
        text = text[: m.start()]
    if (m := SIGNOFF.search(text)) and m.start() > 0.4 * len(text):
        text = text[: m.start()]
    text = text.split("\n-- \n")[0]
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()

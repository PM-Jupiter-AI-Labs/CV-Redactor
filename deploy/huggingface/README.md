---
title: CV Redactor
emoji: 🗂
colorFrom: indigo
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
short_description: Strip names, contact details and photos from candidate CVs
---

# CV Redactor

Removes names, contact details, addresses and photographs from candidate CVs, so
they can be reviewed without identifying the person.

Upload a PDF or DOCX, confirm which words are the surname — that part cannot be
automated, because nothing marks "Sharma" as a name rather than a place — and
download the redacted copy.

## What this Space does with your files

Nothing is stored. Uploaded files live in a temporary directory for the duration
of one request and are deleted before it returns; the redacted copy is handed
back to your browser and the Space keeps no record of either.

That said, **this is a public Space with no authentication.** Anything uploaded
here is processed on Hugging Face's infrastructure. Use it with sample or
synthetic CVs. For real candidate data, run it yourself — the source is a
command-line tool and a Docker Compose file, and it works entirely offline.

## Source

<https://github.com/PM-Jupiter-AI-Labs/CV-Redactor>

Everything is deterministic regex and PDF surgery: no model, no API key, no
network calls at runtime.

# Project documentation

[Technical guide](TECHNICAL_GUIDE.md) is the editable source of the architecture,
workflows, access rules, state retention, configuration and operational procedures.
[PDF edition](reference/DocuMind_Chemistry_Technical_Documentation.pdf) is the generated
print edition with a linked contents page and document outline.

The guide describes the single-VM implementation at baseline commit
`f645799d99fa7c36317942def64215f5457d367f`. Proposed capacity changes are identified
separately from implemented behavior. Defaults are not a snapshot of every deployment's
private settings. No private documents, credentials or server account details appear here.

## Figures

- [System architecture](diagrams/system-architecture.svg)
- [Document ingestion and publication](diagrams/document-ingestion.svg)
- [Student question processing](diagrams/student-question.svg)
- [Hybrid retrieval](diagrams/hybrid-retrieval.svg)

SVG is the editable figure source; PNG is used in GitHub and PDF for reliable rendering.
Component logos identify the technology. Logical services use original symbols.
Devicon assets are pinned by commit and SHA-256 in `assets/icons/sources.json`; the
upstream MIT license is retained in `assets/icons/DEVICON_LICENSE.txt`. Product marks
remain the property of their owners; inclusion does not imply endorsement.

## Rebuild

Use Python with ReportLab and Pillow and Node.js with Sharp installed in an approved
build environment. Documentation-only dependencies are listed in
`tools/requirements.txt` and `tools/package.json`; they are separate from app runtime
dependencies. From the repository root:

```sh
python -m pip install -r docs/tools/requirements.txt
npm install --prefix docs/tools
node docs/tools/build_diagrams.mjs
python docs/tools/build_documentation.py
```

The figure builder reads only checked-in icon files. Regeneration does not call Groq,
Pinecone or Azure. The PDF builder reads the Markdown and generated PNGs. Font rendering
can differ across environments; inspect all rendered PDF pages before publishing.
`fetch_icons.py` is an optional network-dependent asset refresh tool and is not needed
for a normal rebuild. Review any new icon source/version and license before updating.

Keep private QA render images outside the repository. Commit the guide, SVG/PNG figures,
icon provenance, builder changes and generated PDF together when updating documentation.

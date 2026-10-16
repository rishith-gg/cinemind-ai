# Report tools
Rebuild the course report and deck (outside the app; needs Node with `docx@9` and `pptxgenjs@3`, and matplotlib):
```bash
uv run --with matplotlib python -I charts.py ../figures   # figures (numbers from docs/EVALUATION.md)
mkdir -p fig && cp ../figures/*.png fig/                  # build.js reads ./fig
npm install docx@9 pptxgenjs@3 && node build.js && node deck.js
```
Edit `links.json` (PPT, video, repository links) before rebuilding. Export the PDF from Word (File → Save As → PDF).

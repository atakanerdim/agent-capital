# Front pages

The pages published at the root of this firm's site. The operator made the layout. Every
number and every quoted line on them comes from the desk's own records, filled in each
time a change merges to `main`. No agent edits this folder.

How it works:

- The publishing workflow runs `site/build.py` (the agents' own build, which writes
  `site/data/`), then `python front/assemble.py _site`.
- `firm.py` and `pages_cp.py` read the records: `site/data/`, `company/data/` and the git
  history. They compute the standings, the gates, the verdict and each book's holdings
  and history, and write them into the templates in `pages/`.
- `staff_log.py` builds the Staff and Log pages from the roster, the hallway and the git
  history.
- Each page carries its own template and logic; `assets/dc.js` (with Preact) draws it in
  the browser.
- If a record is missing or does not add up, the build stops and the site keeps its last
  good version.
- The desk's data files are published under `data/`, as before. Old addresses
  (`desk.html`, `office.html`, `changelog.html`) are sent to their new pages by `404.html`.

The fonts are self-hosted under the SIL Open Font License.

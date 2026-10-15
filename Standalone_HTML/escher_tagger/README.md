# escher_tagger

A bookmarklet that adds a small panel to any [Escher](https://escher.github.io) metabolic map, so you can assign values to reactions and metabolites by selecting them on the map instead of looking up IDs and hand-writing a data file. It works on the standalone HTMLs from [jt_escher](../../CLI_tools/jt_escher/) (Escher 1.7.3), on escher.github.io, and on newer Escher builds.

## Features

- Select nodes in Escher as usual (Select mode: click, shift-click, or drag a box); the panel lists the selected reactions and metabolites by BiGG ID
- **Set** a value on the selection, **Highlight** it with a fixed value, or **Clear** it
- Values are loaded into Escher as ordinary reaction and metabolite data, so Escher's own color and size scales (Settings menu) control how they look
- **Notes**: attach a note to the selection; it's recorded in the export and can also be dropped on the map as a text label (kept by Map > Save map JSON)
- **Export JSON** (values + notes) or **CSV** (`type,id,value`); **Import** reloads a previous export or a plain Escher `{id: value}` data file
- **Undo** for value and note changes
- Keeps any reaction/metabolite data already loaded in the page
- Entirely client-side: no server, installation, uploads, or persistent storage

## Install

Open `escher_tagger.html` in a browser and drag the **Escher Tagger** button to your bookmarks bar. In Firefox, if dragging doesn't work, right-click the button and choose Bookmark Link.

## Usage

1. Open an Escher map, e.g. an HTML generated with `escher-cli`.
2. Click the bookmark. The panel appears at the top right; click the bookmark again to hide or show it. The panel can be dragged by its header.
3. In Escher, switch to Select mode (Edit menu, or `v`) and select nodes.
4. Type a value and press **Set** (or Enter), or press **Highlight**.
5. Export the values, and save the map with Map > Save map JSON if you added notes as text labels.

### How a selection maps to reactions

- **markers** (default): a reaction counts as selected when one of its marker nodes (the small midpoint nodes, not metabolites) is selected. Dragging a box over the middle of a reaction grabs its marker.
- **any node**: a reaction counts as selected when any of its nodes is selected, including its metabolites. This also picks up neighbouring reactions that share a selected metabolite.

The **Reactions** and **Metabolites** checkboxes choose which of the two the actions apply to.

## Limitations

- Escher keys data by BiGG ID, so every copy of a reaction or metabolite drawn on the map gets the same value.
- Values are numbers; free text goes in notes.
- **Undo** doesn't remove text labels already placed on the map; delete those in Escher.
- Values live in the open tab until exported. Reloading the page discards them.
- Not tested inside Jupyter notebooks; export the map to HTML (`escher-cli` or `Builder.save_html`) and use it there.

## Files

- `escher_tagger.html` — install page; also holds the bookmarklet source. The button is built from that source when the page opens, so edit the code there.
- `README.md` — this file.

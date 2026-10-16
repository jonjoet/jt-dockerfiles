# escher_tagger

A bookmarklet that adds a small panel to any [Escher](https://escher.github.io) metabolic map, so you can assign values to reactions and metabolites by selecting them on the map instead of looking up IDs and hand-writing a data file. It works on the standalone HTMLs from [jt_escher](../../CLI_tools/jt_escher/) (Escher 1.7.3), on escher.github.io, and on newer Escher builds.

## Features

- Select nodes in Escher as usual (Select mode: click, shift-click, or drag a box); the panel lists the selected reactions and metabolites by BiGG ID
- **Set** a value on the selection, **Highlight** it with a fixed value, or **Clear** it
- Values are loaded into Escher as ordinary reaction and metabolite data, so Escher's own color and size scales (Settings menu) control how they look
- **Notes**: attach a note to the selection; it's recorded in the export and can also be dropped on the map as a text label (kept by Map > Save map JSON)
- **Export JSON** (values + notes) or **CSV** (`type,id,value`); **Import** reloads a previous export or a plain Escher `{id: value}` data file
- **Export model**: save the COBRA model loaded in Escher as JSON, unchanged when the original is available (see [Model export](#model-export)); Escher itself has no model export
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

## Model export

Escher draws from its own converted copy of the model: bounds become just reversible/irreversible, reactions that only run backwards are flipped, and display fields are added. The original COBRA JSON is kept only in two cases, and **Export model** returns it byte-for-byte in both:

- **The model embedded in the page.** HTMLs made by `escher-cli` (or `Builder.save_html` with a model) embed the full model, so this is the normal case. Saved as `<model id>.json`.
- **A model loaded from the Model menu after the tagger was started.** The tagger records the file as Escher loads it.

Otherwise, for example a model loaded from the menu before the tagger was started, the tagger rebuilds a COBRA JSON from Escher's copy, saves it as `<map>.model.from_escher.json`, and says so in the panel. The rebuilt model keeps reactions, metabolites, stoichiometry, reversibility, gene rules, objective coefficients, compartments, and annotations, but:

- all bounds become `0/1000` or `-1000/1000`, so exchange limits (e.g. glucose uptake) are lost and FBA results will differ
- reactions that could only run backwards are flipped to forwards (equivalent network, opposite sign)
- genes not used in any gene reaction rule are dropped, as is model-level metadata (ID, name, notes)

Use the rebuilt model for drawing or IDs, not for FBA. Before exporting, the tagger checks that the original's reactions, metabolites, reversibility, and stoichiometry match what Escher has loaded, so a model swapped in through the menu is never exported as the stale embedded one.

## Limitations

- Escher keys data by BiGG ID, so every copy of a reaction or metabolite drawn on the map gets the same value.
- Values are numbers; free text goes in notes.
- **Undo** doesn't remove text labels already placed on the map; delete those in Escher.
- Values live in the open tab until exported. Reloading the page discards them.
- Not tested inside Jupyter notebooks; export the map to HTML (`escher-cli` or `Builder.save_html`) and use it there.

## Files

- `escher_tagger.html` — install page; also holds the bookmarklet source. The button is built from that source when the page opens, so edit the code there.
- `README.md` — this file.

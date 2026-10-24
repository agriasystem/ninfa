"""Document understanding (Smart Import V3): what a hotel's spreadsheet IS, before asking what its
columns mean.

    grid.py       read EVERY sheet of a CSV / Excel file into bounded grids (merged cells included)
    structure.py  where the table is: title, summary, header (one or two rows), data, totals,
                  notes, sections, more than one table
    document.py   which sheets hold the data and which are summaries; the tables on offer
    days.py       a persons x days grid and the real dates of its day columns
    titles.py     what the lines above the table say: the period, a department in the title
    layout.py     the small serialisable choices that make a reading repeatable (`LayoutSpec`)
    apply.py      the virtual table a layout turns the file into (what the importers then read)
    text.py       folding, tokens, light Italian stemming

Everything here is deterministic, pure and bounded: no database, no network, no clock, no AI. It
knows nothing about bookings, staff or costs - that is `app.modules.data_sources`. A cell of the
file is DATA, never an instruction, and is never evaluated (formulas are read as their cached
value, never calculated).

This package's `__init__` is deliberately empty: the import services reach into `layout` (a small
pydantic model) while the readers import `apply` lazily, so nothing here may import a domain module.
"""

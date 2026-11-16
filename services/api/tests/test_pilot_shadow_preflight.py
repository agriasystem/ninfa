"""No personal value of a demo/pilot file can leave in a request to a model: the audit that gates
the real pilot shadow validation, kept as a test.

Every file of the demo environment is read by Smart Import with the gate forced open (so the model
would be asked about each one that has a table) and with a stand-in that only records what it is
handed. Every request is audited: its shape (only the closed evidence), what a person's data looks
like (shapes, the values of the file's own personal columns, found WITHOUT the engine), the name of
the file. Found by the first run of the validation: a column of street addresses under the header
"Street" was sent as an example value. A single finding is a STOP.

No network, no key, no database.
"""

from tests.benchmarks.smart_import_v3.pilot_shadow import canaries_of, discover, preflight


def test_the_demo_environment_has_files_to_validate() -> None:
    files = discover()

    assert len(files) >= 20
    assert {f.card for f in files} == {"bookings", "costs"}


def test_nothing_personal_is_in_any_request_a_demo_file_can_produce() -> None:
    result = preflight(discover())

    assert result["problems"] == []
    assert result["requests_built"] >= 5  # the audit really looked at requests
    assert result["canary_values_checked"] > 1000


def test_the_street_of_the_invoice_with_personal_columns_is_among_what_is_checked() -> None:
    files = {f.id: f for f in discover()}

    values = canaries_of(files["invoices/structured/pii_unmapped_columns.csv"])

    assert "Via Inventata 12" in values

"""How the TEXT dates and amounts of some documents are written - the truth, in one place.

A date or an amount typed as text (`19/10/2026`, `1.237,45`, `$1,234.56`) can be read two ways, and
reading it the wrong way is silent: 03/04 becomes March 4 instead of April 3, 1.234 becomes one
point two instead of one thousand two hundred. The documents listed here were drawn with a known
convention; the benchmark checks the convention Smart Import resolves for them.

Entries are (date order, decimal mark): ``DMY`` | ``MDY`` | ``YMD`` | None, and ``","`` | ``"."`` |
None. A real Excel date or number needs no choice and is not listed. Keys are the case names
without their number.
"""

# slug -> (date order of the text dates, decimal mark of the text amounts)
FORMATS: dict[str, tuple[str | None, str | None]] = {
    # --- staff ---
    "csv_basic": ("DMY", ","),
    "alias_dept_hprev_consuntivo": ("YMD", None),
    "alias_settore_pianificate_lavorate": ("DMY", None),
    "english_planned_actual": ("YMD", "."),
    "dates_us_provable": ("MDY", "."),
    "dates_ambiguous_day_month": ("DMY", None),
    "dates_dotted_text_hours_comma": ("DMY", ","),
    "pii_split_name_email_phone_taxcode": ("DMY", None),
    "office_monthly_hours_report": ("DMY", ","),
    "office_front_desk_roster_csv": ("DMY", ","),
    "header_cells_with_line_breaks_staff": ("DMY", None),
    # --- bookings ---
    "csv_italian_canonical": ("DMY", ","),
    "npren_prenotato_il_dal_al": ("DMY", ","),
    "english_booking_id_created_source": ("YMD", "."),
    "ref_portale_totale_soggiorno": ("DMY", ","),
    "abbreviated_headers": ("DMY", ","),
    "amounts_thousands_dot_comma_decimal": (None, ","),
    "amounts_point_decimal_csv": ("YMD", "."),
    "amounts_with_euro_sign_text": (None, ","),
    "dates_text_italian": ("DMY", None),
    "dates_us_provable_csv": ("MDY", "."),
    "dates_ambiguous_day_month_bookings": ("DMY", None),
    "dates_dotted_and_day_month_name": ("DMY", None),
    "booking_timestamp_with_time": ("YMD", "."),
    "ids_with_leading_zeros_and_numeric": ("DMY", ","),
    "booker_and_guest_names_two_columns": ("YMD", "."),
    "office_channel_manager_extract": ("YMD", "."),
    "office_front_desk_monthly_report": ("DMY", ","),
    "channel_written_as_codes": ("DMY", ","),
    "channel_manager_abbreviations": ("YMD", "."),
    # --- costs ---
    "dates_text_italian_costs": ("DMY", None),
    "dates_iso_csv": ("YMD", "."),
    "dates_ambiguous_us_or_italian": ("DMY", None),
    "amounts_italian_thousands": (None, ","),
    "amounts_us_thousands_csv": ("MDY", "."),
    "amounts_euro_sign_text": (None, ","),
    "net_vat_gross_amount_english": ("YMD", "."),
    "totale_netto_imposta_totale": (None, ","),
    "office_cost_ledger_csv_semicolon": ("DMY", ","),
    "amounts_with_eur_suffix_text": (None, ","),
}

# Some case names exist in more than one kind of data: the card tells them apart.
BY_CARD: dict[tuple[str, str], str] = {
    ("labor", "header_cells_with_line_breaks"): "header_cells_with_line_breaks_staff",
    ("bookings", "dates_ambiguous_day_month"): "dates_ambiguous_day_month_bookings",
    ("costs", "dates_text_italian"): "dates_text_italian_costs",
}

"""ISO 4217 currency codes accepted for property currencies (V1).

A plain snapshot instead of a dependency. Intentionally excluded: precious metals, testing
codes, IMF units and "fund" codes (XAU, XXX, XDR, CHE, USN, ...), which are not pricing
currencies, and withdrawn codes (e.g. HRK, BGN after euro adoption, ZWL). Add a code by editing
this set; it is only enforced by the Pydantic layer (the database checks the 3-letter format).
"""

_CODES = """
    AED AFN ALL AMD ANG AOA ARS AUD AWG AZN BAM BBD BDT BHD BIF BMD BND BOB BRL BSD BTN BWP BYN
    BZD CAD CDF CHF CLP CNY COP CRC CUP CVE CZK DJF DKK DOP DZD EGP ERN ETB EUR FJD FKP GBP GEL
    GHS GIP GMD GNF GTQ GYD HKD HNL HTG HUF IDR ILS INR IQD IRR ISK JMD JOD JPY KES KGS KHR KMF
    KPW KRW KWD KYD KZT LAK LBP LKR LRD LSL LYD MAD MDL MGA MKD MMK MNT MOP MRU MUR MVR MWK MXN
    MYR MZN NAD NGN NIO NOK NPR NZD OMR PAB PEN PGK PHP PKR PLN PYG QAR RON RSD RUB RWF SAR SBD
    SCR SDG SEK SGD SHP SLE SOS SRD SSP STN SVC SYP SZL THB TJS TMT TND TOP TRY TTD TWD TZS UAH
    UGX USD UYU UZS VED VES VND VUV WST XAF XCD XCG XOF XPF YER ZAR ZMW ZWG
"""

ISO_4217_CODES: frozenset[str] = frozenset(_CODES.split())

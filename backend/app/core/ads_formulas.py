"""Names of the Ads markup formulas, shared by the config, the settings store and `view/ads.py`.

Kept free of imports so any layer can read it without a cycle. `view.ads.ADS_MARKUP_FORMULAS`
implements exactly these names (a test pins the two together).
"""

ADS_FORMULA_NAMES = ("costo_extra", "resta_limpio")
DEFAULT_ADS_FORMULA = "costo_extra"

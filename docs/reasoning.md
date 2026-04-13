# Reasoning

Narrative behind the two most fundamental scoping choices in this project:
which grape varieties to model and where to start the time series.

---

## Why these three varieties

### Cabernet Sauvignon

Napa Valley's signature variety and the dominant crop in CDFA District 4 by
volume (92,000+ tons in 2023). It has the deepest and most consistent crush
report history of any variety in the district, making it the strongest
candidate for time-series modeling. Cabernet is also heat-tolerant relative
to other wine grapes, which means its yield and Brix signal reflects thermal
accumulation rather than heat damage — the relationship between GDD and
outcome is cleaner and more interpretable.

### Pinot Noir

Included precisely because it is the opposite of Cabernet in climate
sensitivity. Pinot Noir is one of the most heat-sensitive winegrape varieties:
a few degrees of additional warming during the growing season measurably
compresses its ripening window and can push Brix beyond the optimal range.
This makes it the highest-signal variety for demonstrating climate effects.
Napa Carneros and cooler Napa sub-appellations grow meaningful tonnage, so
the district-level record is credible. Including Pinot alongside Cabernet
allows the model to show variety-specific climate sensitivity — a core
domain contribution of the thesis.

### Chardonnay

The white variety anchor. Chardonnay has a different thermal optimum and
a different water-stress response profile than either red variety. Its
inclusion ensures the model covers the full range of the district's commercial
output and tests whether climate-to-quality relationships generalize across
grape color and phenological timing. Chardonnay is also well-documented in
the viticulture literature, which aids validation.

### Varieties explicitly excluded

Merlot, Petit Verdot, Sauvignon Blanc, and others were excluded because their
Crush Report records in District 4 are too sparse or too recent for credible
multi-decade modeling. Adding them would require imputation strategies that
introduce more noise than signal at this scale.

---

## Why data starts at 1991

The CDFA Grape Crush Report digital archive — the machine-readable Excel files
published by CDFA and mirrored by USDA NASS — begins with the 1991 crop year.
Earlier reports exist but were published as PDFs or paper documents with no
corresponding structured data files. Parsing pre-1991 PDFs would require
substantial OCR and manual validation work that is out of scope for this
project.

Three secondary reasons reinforce 1991 as a sensible start:

1. **Sufficient length for modeling.** Thirty-five seasons (1991–2025) is long
   enough to fit and cross-validate a time-series model and to observe multiple
   full drought cycles, heat waves, and wet years.

2. **PRISM alignment.** PRISM daily grids begin in 1981. Starting CDFA data at
   1991 leaves a 10-year PRISM-only window that can be used for feature
   engineering validation before the joint climate–yield series begins, rather
   than forcing an awkward truncation of the climate features.

3. **Post-phylloxera replanting.** The mid-to-late 1980s saw widespread
   phylloxera-driven vineyard replanting across Napa. By 1991 the replanted
   blocks were entering production. Starting here reduces the structural break
   caused by wholesale vine removal and replanting, which would distort
   tonnage trends in the early part of the series.

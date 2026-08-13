"""Artifact rendering. Deterministic and templated.

No language model appears anywhere in this package. A document that counsel
reviews, that an underwriter relies on, and that may be produced in discovery
has to render identically from identical data every time.
"""

from truestory.reports.eo_report import render_pdf

__all__ = ["render_pdf"]

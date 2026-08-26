"""The five stages a CV goes through, in order.

    1. parse      file        -> raw text + file forensics        (no LLM)
    2. normalize  raw text    -> CandidateProfile, stored          (LLM, once per CV)
    3. jobspec    job advert  -> JobProfile, stored                (LLM, once per job)
    4. match      profile x job -> per-requirement result          (no LLM)
    5. rank       matches     -> ordered shortlist with tiers      (no LLM)

Only stages 2 and 3 cost anything. Stage 2 runs once per CV for the lifetime of the
document, so screening a stored candidate against a new vacancy is free and instant -
which is what makes thousands of CVs and many vacancies practical.
"""

from . import jobspec, match, normalize, parse, rank

__all__ = ["parse", "normalize", "jobspec", "match", "rank"]

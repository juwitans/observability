"""improve/ — phase 1.5: the automated improvement loop (IMPLEMENTATION.md §5.1).

harvest.py     low scores / fired detectors -> dataset items (cron-able)
judge_check.py judge-vs-human agreement (meta-eval, gates optimization)
optimize.py    DSPy compile: dataset + judge metric -> new prompt version
"""

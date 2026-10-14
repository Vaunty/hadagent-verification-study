# Evidence figures

These four figures interpret the repository's saved P012 and P013 evidence and the documented HadAgent scope boundary. They do not add experimental observations.

- `framework-scope` maps the paper's proposed components to the paths reached by this study.
- `verification-boundary` illustrates the P010/P012 known-answer control.
- `score-repair` plots the P012 finite-grid acceptance counts.
- `honest-baseline` plots the paired P013 scores and its zero eligible-trial denominator.

Each figure is available as editable SVG and README-friendly PNG. `figure_data.json` contains the audited aggregate values and evidence hashes. `generate_figures.py` rebuilds all four files with Matplotlib and does not call a model, endpoint, or external service.

```powershell
python docs/assets/generate_figures.py
```

The figures use phrases such as “does not establish” to mark the evidence boundary. They should not be detached from their captions or used to imply network consensus, deployed impact, a population attack rate, or independent human validation.

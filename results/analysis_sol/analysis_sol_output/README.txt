Run source('analysis_sol.R') from the project root, with inputs in results/.
Alternatively: Rscript analysis_sol.R INPUT_DIRECTORY OUTPUT_DIRECTORY
Bootstrap: 10000 percentile resamples; seed 20260918. CIs are pointwise.
Upload the entire output folder to Overleaf and compile results_standalone.tex.
For thesis inclusion, adjust relative figure paths as needed; pagination depends on the thesis class.
Inspect the PDFs and residual diagnostics before publication. No LaTeX compilation is performed by this script.
Wilcoxon inference uses symmetry; sign tests are supplementary and target nonzero direction balance.
All-available sensitivity adjusts its own family of 12 tests; it is not part of the primary family.
Model identity and configuration come from supplied metadata, not an independent API verification.

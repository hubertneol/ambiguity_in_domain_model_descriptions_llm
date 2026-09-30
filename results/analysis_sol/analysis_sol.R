# analysis_sol.R -- paired analysis of the GPT-5.6 Sol experiment
# Run in RStudio: source("analysis_sol.R")
# Or: Rscript analysis_sol.R results analysis_sol_output
# Required packages (install once, if necessary):
# install.packages(c("dplyr", "tidyr", "readr", "jsonlite", "ggplot2", "knitr"))
# Optional mixed models: install.packages("lmerTest")
# Inputs are never modified. All estimates in exported text are computed below.
# Runtime note: authored in an environment without R; execution requires R locally.

required <- c("dplyr", "tidyr", "readr", "jsonlite", "ggplot2", "knitr")
missing <- required[!vapply(required, requireNamespace, logical(1), quietly = TRUE)]
if (length(missing)) stop("Install required packages: install.packages(c(",
  paste(sprintf('"%s"', missing), collapse = ", "), "))")
suppressPackageStartupMessages({library(dplyr); library(tidyr); library(ggplot2)})
args <- commandArgs(trailingOnly = TRUE)

# Locate this script so inputs resolve relative to it, not to the working
# directory. Without this the defaults break when the script is sourced from
# its own folder in RStudio, which is the usual way it gets run.
script_path <- function() {
  cmd <- grep("^--file=", commandArgs(FALSE), value = TRUE)   # Rscript
  if (length(cmd)) return(normalizePath(sub("^--file=", "", cmd[1]), mustWork = FALSE))
  for (i in seq_len(sys.nframe())) {                           # source()
    ofile <- sys.frame(i)$ofile
    if (!is.null(ofile)) return(normalizePath(ofile, mustWork = FALSE))
  }
  NA_character_
}
script_dir <- tryCatch(dirname(script_path()), error = function(e) NA_character_)

# First existing candidate wins: explicit argument, environment variable, the
# working directory, the script's own folder, then its parent (the script lives
# in results/analysis_sol/, so the parent is results/).
resolve_input_dir <- function() {
  if (length(args)) return(args[1])
  env <- Sys.getenv("SOL_INPUT_DIR", "")
  candidates <- c(if (nzchar(env)) env,
                  "results", "upload", ".",
                  if (!is.na(script_dir)) c(script_dir,
                                            file.path(script_dir, ".."),
                                            file.path(script_dir, "..", "..", "results")))
  has_inputs <- function(d) dir.exists(d) && file.exists(file.path(d, "results.csv"))
  hit <- Filter(has_inputs, candidates)
  if (length(hit)) return(normalizePath(hit[1]))
  stop("Could not locate the input directory. Pass it explicitly:\n",
       "  Rscript analysis_sol.R /path/to/results /path/to/output")
}
input_dir <- resolve_input_dir()
output_dir <- if (length(args) > 1) args[2] else {
  if (!is.na(script_dir)) file.path(script_dir, "analysis_sol_output") else "analysis_sol_output"
}
message("input_dir : ", input_dir)
message("output_dir: ", output_dir)
for (d in c("", "figures", "tables", "data"))
  dir.create(file.path(output_dir, d), recursive = TRUE, showWarnings = FALSE)
SEED <- 20260918L
B <- 10000L
set.seed(SEED)
metrics <- c("class_score", "attribute_score", "association_score")
metric_labels <- c(class_score = "Classes", attribute_score = "Attributes",
                   association_score = "Associations")
versions <- paste0("V", 0:4)
# prefer = FALSE: several matches mean an accidental duplicate (e.g. a second
# browser download), so refuse to guess.
# prefer = TRUE: the names are an ordered preference list, so take the first
# that exists. Used for the generation log, where the filtered gpt-5.6-sol
# export must win over the mixed-model original.
pick <- function(names, prefer = FALSE) {
  paths <- file.path(input_dir, names)
  found <- paths[file.exists(paths)]
  if (!length(found)) stop("Missing input: ", paste(names, collapse = " or "))
  if (prefer) {
    if (length(found) > 1)
      message("using ", basename(found[1]), " (ignoring ",
              paste(basename(found[-1]), collapse = ", "), ")")
    return(found[1])
  }
  if (length(found) > 1) stop("Ambiguous input; keep only one of: ", paste(found, collapse = ", "))
  found[1]
}
paths <- c(primary = pick(c("results.csv", "results(1).csv")),
           replication = pick("results_run2.csv"),
           records = pick("records_225_sol.jsonl"),
           log = pick(c("generation_log_sol.csv", "generation_log.csv"), prefer = TRUE),
           pairs = pick("noise_floor_pairs.csv"),
           summary = pick("noise_floor_summary.csv"))
csv <- function(path) readr::read_csv(path, show_col_types = FALSE,
                                     na = c("", "NA", "null"))
raw <- csv(paths["primary"])
run2 <- csv(paths["replication"])
records <- bind_rows(lapply(readLines(paths["records"], warn = FALSE), jsonlite::fromJSON))
if (!"error" %in% names(records)) records$error <- NA_character_
log_raw <- csv(paths["log"])
old_pairs <- csv(paths["pairs"])
old_summary <- csv(paths["summary"])
write_csv <- function(x, name) readr::write_csv(x, file.path(output_dir, name), na = "")
write_csv(tibble(file = names(paths), source = basename(paths),
                 md5 = unname(tools::md5sum(paths))), "data/input_manifest.csv")
validate <- function(x, expected_run, allowed_versions) {
  need <- c("case_id", "version", "run", metrics)
  if (!all(need %in% names(x))) stop("Missing score columns")
  if (anyNA(x[c("case_id", "version", "run")])) stop("Missing observation key")
  if (anyDuplicated(x[c("case_id", "version", "run")])) stop("Duplicate observation key")
  if (!all(x$run == expected_run) || !all(x$version %in% allowed_versions))
    stop("Unexpected run or version")
  for (m in metrics) {
    if (!is.numeric(x[[m]])) stop("Non-numeric score: ", m)
    if (any(!is.na(x[[m]]) & (!is.finite(x[[m]]) | x[[m]] < 0 | x[[m]] > 1)))
      stop("Invalid score range: ", m)
  }
  if ("model_name" %in% names(x) && any(is.na(x$model_name) | x$model_name != "gpt-5.6-sol"))
    stop("Unexpected or missing model provenance")
  x
}
raw <- validate(raw, 1, versions)
run2 <- validate(run2, 2, "V0")
cases <- sort(unique(raw$case_id))
stopifnot(length(cases) == 45L, nrow(raw) == 225L, nrow(run2) == 45L,
          setequal(cases, run2$case_id))
grid <- tidyr::expand_grid(case_id = cases, version = versions)
stopifnot(nrow(anti_join(grid, raw, by = c("case_id", "version"))) == 0)
raw <- raw %>% mutate(valid = if_all(all_of(metrics), ~ !is.na(.x)))
run2 <- run2 %>% mutate(valid = if_all(all_of(metrics), ~ !is.na(.x)))
complete_ids <- raw %>% group_by(case_id) %>% summarise(ok = all(valid), .groups = "drop") %>%
  filter(ok) %>% pull(case_id)
if (length(complete_ids) < 3) stop("Too few complete cases")
stopifnot(!anyDuplicated(records[c("case_id", "version", "run")]))
record_check <- inner_join(raw, records, by = c("case_id", "version", "run"), suffix = c(".csv", ".json"))
stopifnot(nrow(record_check) == 225)
for (m in metrics) stopifnot(isTRUE(all.equal(record_check[[paste0(m, ".csv")]],
  record_check[[paste0(m, ".json")]], tolerance = 1e-12)))
exclusions <- raw %>% filter(!valid) %>% select(case_id, version, run) %>%
  left_join(records %>% select(case_id, version, run, error), by = c("case_id", "version", "run")) %>%
  mutate(error = coalesce(error, "Missing score; no error recorded"),
         reason = sub("\n.*", "", error))
completeness <- tibble(item = c("Benchmark cases", "Intended observations", "Successful observations",
  "Failed observations", "Complete cases", "Excluded cases", "Primary observations"),
  n = c(length(cases), nrow(raw), sum(raw$valid), sum(!raw$valid), length(complete_ids),
        length(cases) - length(complete_ids), 5 * length(complete_ids)))
long <- raw %>% pivot_longer(all_of(metrics), names_to = "metric", values_to = "score")
primary <- long %>% filter(case_id %in% complete_ids)
make_deltas <- function(x) {
  x %>% filter(version != "V0", !is.na(score)) %>%
    inner_join(x %>% filter(version == "V0", !is.na(score)) %>%
      select(case_id, metric, baseline = score), by = c("case_id", "metric")) %>%
    mutate(delta = score - baseline, abs_delta = abs(delta))
}
deltas <- make_deltas(primary)
all_deltas <- make_deltas(long)
replication <- run2 %>% pivot_longer(all_of(metrics), names_to = "metric", values_to = "run2") %>%
  select(case_id, metric, run2) %>% inner_join(long %>% filter(version == "V0") %>%
    select(case_id, metric, run1 = score), by = c("case_id", "metric")) %>%
  filter(!is.na(run1), !is.na(run2)) %>% mutate(delta = run2 - run1, abs_delta = abs(delta))

# Percentile bootstrap: resample cases, never treat conditions as independent.
# All CIs are pointwise, not simultaneous or multiplicity-adjusted.
boot_ci <- function(x, fun = mean) {
  if (!length(x)) return(c(NA_real_, NA_real_))
  draws <- replicate(B, fun(sample(x, length(x), replace = TRUE)))
  unname(quantile(draws, c(.025, .975), type = 7))
}
summary_values <- function(x) {
  ci <- boot_ci(x)
  tibble(n = length(x), mean = mean(x), sd = sd(x), median = median(x),
    iqr = IQR(x), min = min(x), max = max(x), ci_low = ci[1], ci_high = ci[2])
}
descriptive <- primary %>% group_by(version, metric) %>%
  group_modify(~ summary_values(.x$score)) %>% ungroup()
effect_summary <- function(x) {
  x %>% group_by(version, metric) %>% group_modify(~ {
    z <- .x$delta
    summary_values(z) %>% mutate(mean_v0 = mean(.x$baseline), mean_variant = mean(.x$score),
      mean_abs = mean(abs(z)), median_abs = median(abs(z)), improved = sum(z > 0),
      unchanged = sum(z == 0), worsened = sum(z < 0),
      improved_pct = 100 * mean(z > 0), unchanged_pct = 100 * mean(z == 0),
      worsened_pct = 100 * mean(z < 0))
  }) %>% ungroup()
}
effects <- effect_summary(deltas)
rep_summary <- replication %>% group_by(metric) %>% group_modify(~ {
  aci <- boot_ci(.x$abs_delta)
  summary_values(.x$delta) %>% mutate(mean_abs = mean(.x$abs_delta),
    median_abs = median(.x$abs_delta), iqr_abs = IQR(.x$abs_delta), max_abs = max(.x$abs_delta),
    abs_ci_low = aci[1], abs_ci_high = aci[2], identical = sum(.x$delta == 0),
    identical_pct = 100 * mean(.x$delta == 0))
}) %>% ungroup()

# Wilcoxon tests use normal approximation, tie correction and continuity correction.
# Zeros are omitted from ranks. Signed-rank inference assumes symmetric differences;
# it is not, in general, a test of the arithmetic mean or unrestricted median.
test_one <- function(z) {
  nz <- z[z != 0]
  if (!length(nz)) return(tibble(W = 0, p_raw = 1, rank_biserial = 0, n_nonzero = 0L))
  ranks <- rank(abs(nz), ties.method = "average")
  wt <- wilcox.test(z, mu = 0, exact = FALSE, correct = TRUE)
  tibble(W = unname(wt$statistic), p_raw = wt$p.value,
    rank_biserial = sum(sign(nz) * ranks) / sum(ranks), n_nonzero = length(nz))
}
infer <- function(x) x %>% group_by(version, metric) %>%
  group_modify(~ test_one(.x$delta)) %>% ungroup() %>% mutate(p_holm = p.adjust(p_raw, "holm"))
tests <- infer(deltas) %>% left_join(effects, by = c("version", "metric"))
stopifnot(nrow(tests) == 12L, all(tests$n == length(complete_ids)),
          all(tests$p_holm >= tests$p_raw - 1e-12),
          all(effects$improved + effects$unchanged + effects$worsened == effects$n))
sensitivity <- infer(all_deltas) %>% left_join(effect_summary(all_deltas), by = c("version", "metric"))
# Sign tests relax signed-rank symmetry, but test direction balance among nonzero pairs.
sign_tests <- deltas %>% group_by(version, metric) %>% group_modify(~ {
  z <- .x$delta[.x$delta != 0]
  tibble(n_nonzero = length(z), p_raw = if (length(z)) binom.test(sum(z > 0), length(z))$p.value else 1)
}) %>% ungroup() %>% mutate(p_holm = p.adjust(p_raw, "holm"))
# Conservative planning approximation: Bonferroni alpha=.05/12, not exact Wilcoxon power.
mde <- effects %>% transmute(version, metric, n, sd_delta = sd,
  alpha = .05 / 12, power = .80,
  mde_normal = (qnorm(1 - .05 / 24) + qnorm(.80)) * sd / sqrt(n))

# Compare absolute magnitudes on the SAME cases; dependence through V0 is preserved.
magnitude_pairs <- deltas %>% inner_join(replication %>%
  select(case_id, metric, replication_delta = delta, replication_abs = abs_delta),
  by = c("case_id", "metric")) %>% mutate(abs_excess = abs_delta - replication_abs)
magnitude <- magnitude_pairs %>% group_by(version, metric) %>% group_modify(~ {
  ci <- boot_ci(.x$abs_excess)
  tibble(n = nrow(.x), mean_abs_variant = mean(.x$abs_delta),
    mean_abs_replication = mean(.x$replication_abs), median_abs_variant = median(.x$abs_delta),
    median_abs_replication = median(.x$replication_abs), mean_abs_excess = mean(.x$abs_excess),
    ci_low = ci[1], ci_high = ci[2])
}) %>% ungroup()

# Supplied noise summaries are rounded to six decimals; equality counts may use rounding.
pair_check <- old_pairs %>% rename(metric = score) %>% full_join(replication,
  by = c("case_id", "metric"), suffix = c(".supplied", ".source")) %>%
  mutate(verified = !is.na(diff) & !is.na(delta) &
    abs(diff - delta) <= 1.1e-6 & abs(abs_diff - abs_delta) <= 1.1e-6 &
    abs(run1.supplied - run1.source) <= 1.1e-6 & abs(run2.supplied - run2.source) <= 1.1e-6)
summary_check <- old_summary %>% rename(metric = score) %>%
  full_join(rep_summary %>% select(metric, n, mean_abs, median_abs, max_abs, sd,
                                 mean_signed = mean, identical, identical_pct),
            by = "metric", suffix = c(".supplied", ".source"))
if (any(!pair_check$verified | is.na(pair_check$verified))) warning("Noise pair verification mismatch")
for (nm in c("mean_abs", "median_abs", "max_abs", "sd", "mean_signed", "identical", "identical_pct")) {
  tol <- if (nm == "identical_pct") .011 else if (nm == "identical") 0 else 1.1e-6
  summary_check[[paste0(nm, "_verified")]] <-
    abs(summary_check[[paste0(nm, ".supplied")]] - summary_check[[paste0(nm, ".source")]]) <= tol
}
summary_check$n_verified <- summary_check$n_cases == summary_check$n
if (any(!as.matrix(select(summary_check, ends_with("_verified"))), na.rm = TRUE))
  warning("Supplied noise summary mismatch; use recomputed source statistics")

log <- log_raw %>% filter(status == "generated", api_model == "gpt-5.6-sol") %>%
  arrange(timestamp) %>% group_by(case_id, version, run) %>% slice_tail(n = 1) %>% ungroup()
provenance <- raw %>% select(case_id, version, run) %>% left_join(log, by = c("case_id", "version", "run"))
if (anyNA(provenance$status)) warning("Some primary generations lack matching provenance")
tokens <- provenance %>% group_by(version) %>% summarise(n = n(),
  mean_total_tokens = mean(total_tokens, na.rm = TRUE),
  sum_total_tokens = sum(total_tokens, na.rm = TRUE), .groups = "drop")

# Optional complementary model; never silently required for the primary analysis.
mixed <- tibble()
variance <- tibble()
if (requireNamespace("lmerTest", quietly = TRUE)) {
  for (m in metrics) {
    dat <- primary %>% filter(metric == m) %>% mutate(version = factor(version, levels = versions))
    fit <- lmerTest::lmer(score ~ version + (1 | case_id), data = dat, REML = TRUE)
    co <- as.data.frame(coef(summary(fit)))
    mixed <- bind_rows(mixed, tibble(metric = m, term = rownames(co), estimate = co$Estimate,
      se = co$`Std. Error`, df = co$df, p = co$`Pr(>|t|)`,
      ci_low = co$Estimate - qt(.975, co$df) * co$`Std. Error`,
      ci_high = co$Estimate + qt(.975, co$df) * co$`Std. Error`))
    vc <- as.data.frame(lme4::VarCorr(fit))
    cv <- vc$vcov[vc$grp == "case_id"]; rv <- sigma(fit)^2
    variance <- bind_rows(variance, tibble(metric = m, case_variance = cv,
      residual_variance = rv, ICC = cv / (cv + rv), singular = lme4::isSingular(fit)))
    pdf(file.path(output_dir, "figures", paste0("diagnostics_", m, ".pdf")), width = 8, height = 4)
    par(mfrow = c(1, 2)); plot(fitted(fit), resid(fit), xlab = "Fitted", ylab = "Residual")
    abline(h = 0, lty = 2); qqnorm(resid(fit)); qqline(resid(fit)); dev.off()
  }
} else message("Optional mixed models skipped: install lmerTest to include them.")

objects <- list(long_scores = long, primary_scores = primary, paired_deltas = deltas,
  replication_pairs = replication, completeness = completeness, exclusions = exclusions,
  descriptives = descriptive, effects = effects, primary_tests = tests,
  available_pair_sensitivity = sensitivity, sign_test_sensitivity = sign_tests,
  replication_summary = rep_summary, magnitude_comparison = magnitude,
  mde_sensitivity = mde, noise_pair_verification = pair_check,
  noise_summary_verification = summary_check, generation_provenance = provenance,
  token_summary = tokens)
if (nrow(mixed)) { objects$mixed_effects <- mixed; objects$variance_components <- variance }
for (nm in names(objects)) write_csv(objects[[nm]], paste0("data/", nm, ".csv"))

# Vector PDF figures. Full data remain in CSV; the compact Results section uses a subset.
palette <- c(V0 = "#333333", V1 = "#0072B2", V2 = "#E69F00", V3 = "#009E73", V4 = "#CC79A7",
             Replication = "#666666")
theme_set(theme_minimal(base_size = 10) + theme(panel.grid.minor = element_blank(),
  legend.position = "bottom", strip.text = element_text(face = "bold")))
facets <- labeller(metric = metric_labels)
save_plot <- function(p, name, width = 8, height = 3.4) {
  ggsave(file.path(output_dir, "figures", name), p, width = width, height = height,
         device = "pdf", useDingbats = FALSE)
}
p1 <- ggplot(descriptive, aes(version, mean, color = version)) +
  geom_errorbar(aes(ymin = ci_low, ymax = ci_high), width = .12) + geom_point(size = 2) +
  facet_wrap(~ metric, labeller = facets) + scale_color_manual(values = palette) +
  coord_cartesian(ylim = c(0, 1)) + labs(x = NULL, y = "Mean similarity (95% bootstrap CI)") +
  guides(color = "none")
save_plot(p1, "fig1_condition_means.pdf")
slope <- bind_rows(deltas %>% transmute(case_id, metric, version, endpoint = "V0", value = baseline),
                   deltas %>% transmute(case_id, metric, version, endpoint = "Variant", value = score))
p2 <- ggplot(slope, aes(endpoint, value, group = case_id)) + geom_line(alpha = .3, color = "#0072B2") +
  geom_point(size = .45, alpha = .45) + facet_grid(metric ~ version, labeller = facets) +
  labs(x = NULL, y = "Similarity")
save_plot(p2, "fig2_paired_case_changes.pdf", 8, 6)
distribution <- bind_rows(deltas %>% select(case_id, metric, version, delta),
  replication %>% transmute(case_id, metric, version = "Replication", delta)) %>%
  mutate(version = factor(version, levels = c(paste0("V", 1:4), "Replication")))
centres <- bind_rows(effects %>% select(version, metric, mean, ci_low, ci_high),
  rep_summary %>% mutate(version = "Replication") %>% select(version, metric, mean, ci_low, ci_high))
p3 <- ggplot(distribution, aes(version, delta, color = version)) + geom_hline(yintercept = 0, linetype = 2) +
  geom_point(position = position_jitter(width = .12, height = 0, seed = SEED), alpha = .35, size = .9) +
  geom_errorbar(data = centres, aes(y = mean, ymin = ci_low, ymax = ci_high), width = .15, linewidth = .7) +
  geom_point(data = centres, aes(y = mean), size = 2.2, shape = 18) +
  facet_wrap(~ metric, labeller = facets) + scale_color_manual(values = palette) +
  labs(x = NULL, y = "Paired score difference", caption = "Points: cases; diamonds: means; bars: pointwise 95% bootstrap CIs.\nReplication is empirical baseline variability, not a significance threshold.") +
  guides(color = "none") + theme(axis.text.x = element_text(angle = 30, hjust = 1))
save_plot(p3, "fig3_effects_and_replication.pdf", 8, 4.2)
order_ids <- primary %>% filter(version == "V0") %>% group_by(case_id) %>%
  summarise(baseline = mean(score), .groups = "drop") %>% arrange(baseline) %>% pull(case_id)
p4 <- ggplot(primary %>% mutate(case_id = factor(case_id, levels = order_ids)), aes(version, case_id, fill = score)) +
  geom_tile() + facet_wrap(~ metric, labeller = facets) + scale_fill_viridis_c(limits = c(0, 1)) +
  labs(x = NULL, y = NULL, fill = "Similarity") + theme(axis.text.y = element_text(size = 6))
save_plot(p4, "fig4_case_heatmap.pdf", 8, 8)
p5 <- ggplot(raw, aes(version, factor(case_id, levels = rev(cases)), fill = valid)) + geom_tile(color = "white") +
  scale_fill_manual(values = c(`TRUE` = "#0072B2", `FALSE` = "#D55E00"),
                    labels = c(`TRUE` = "Successful", `FALSE` = "Failed")) +
  labs(x = NULL, y = NULL, fill = NULL) + theme(axis.text.y = element_text(size = 6))
save_plot(p5, "fig5_completeness.pdf", 5, 8)
p6 <- ggplot(distribution, aes(version, abs(delta), fill = version)) + geom_boxplot(outlier.size = .6) +
  facet_wrap(~ metric, labeller = facets) + scale_fill_manual(values = palette) +
  labs(x = NULL, y = "Absolute paired difference") + guides(fill = "none") +
  theme(axis.text.x = element_text(angle = 30, hjust = 1))
save_plot(p6, "fig6_absolute_differences.pdf")

# LaTeX tables use booktabs; long diagnostic tables are supplementary.
fmt <- function(x) formatC(x, digits = 3, format = "f")
pformat <- function(x) ifelse(x < .001, "<0.001", fmt(x))
ci_text <- function(lo, hi) paste0("[", fmt(lo), ", ", fmt(hi), "]")
table_tex <- function(x, filename, caption) {
  tex <- knitr::kable(as.data.frame(x), format = "latex", booktabs = TRUE,
                      row.names = FALSE, escape = TRUE, caption = caption)
  writeLines(as.character(tex), file.path(output_dir, "tables", filename))
}
table_tex(completeness, "table1_completeness.tex", "Data completeness.")
table_tex(effects %>% transmute(Metric = unname(metric_labels[metric]), Condition = version,
  V0 = fmt(mean_v0), Variant = fmt(mean_variant), Mean = fmt(mean), Median = fmt(median),
  `95% CI` = ci_text(ci_low, ci_high), Better = improved, Equal = unchanged, Worse = worsened),
  "table2_effects.tex", "Complete-case paired effects. Equality means exactly equal source scores.")
table_tex(tests %>% transmute(Metric = unname(metric_labels[metric]), Condition = version, n,
  W, p = pformat(p_raw), Holm = pformat(p_holm), Mean = fmt(mean),
  `95% CI` = ci_text(ci_low, ci_high), RBC = fmt(rank_biserial)),
  "table3_inference.tex", "Primary signed-rank tests; Holm correction across all 12 tests. CIs describe mean differences, not the signed-rank estimand.")
table_tex(exclusions %>% select(case_id, version, reason), "exclusions.tex", "Failed evaluations and recorded reasons.")
table_tex(rep_summary %>% transmute(Metric = unname(metric_labels[metric]), n,
  Signed = fmt(mean), `Mean absolute` = fmt(mean_abs), `Median absolute` = fmt(median_abs),
  Maximum = fmt(max_abs), Identical = identical), "replication.tex", "Repeated-baseline variability.")

# A four-page standalone wrapper and a Results fragment. Actual pagination depends
# on the thesis layout; the explicit page breaks keep the standalone draft compact.
tex_escape <- function(x) {
  x <- gsub("_", "\\_", x, fixed = TRUE)
  x <- gsub("%", "\\%", x, fixed = TRUE)
  x <- gsub("&", "\\&", x, fixed = TRUE)
  x
}
fig <- function(name, caption, height = "0.30\\textheight") paste0(
  "\\begin{center}\\includegraphics[width=\\linewidth,height=", height,
  ",keepaspectratio]{figures/", name, "}\\par\\small ", caption, "\\end{center}")
excluded_names <- setdiff(cases, complete_ids)
reason_text <- if (nrow(exclusions)) paste(tex_escape(unique(exclusions$reason)), collapse = "; ") else "None"
baseline <- descriptive %>% filter(version == "V0")
baseline_text <- paste(sprintf("%s: mean %s (SD %s; range %s--%s)",
  unname(metric_labels[baseline$metric]), fmt(baseline$mean), fmt(baseline$sd), fmt(baseline$min), fmt(baseline$max)), collapse = "; ")
rep_text <- paste(sprintf("%s: signed mean %s, mean absolute difference %s and median absolute difference %s (%d/%d exactly identical)",
  unname(metric_labels[rep_summary$metric]), fmt(rep_summary$mean), fmt(rep_summary$mean_abs),
  fmt(rep_summary$median_abs), rep_summary$identical, rep_summary$n), collapse = "; ")
condition_text <- vapply(metrics, function(m) {
  z <- tests %>% filter(metric == m) %>% arrange(version)
  paste0("\\paragraph{", metric_labels[m], ".} ", paste(sprintf(
    "%s: mean difference %s, 95\\%% CI %s, median %s, Holm-adjusted $p$ %s", z$version,
    fmt(z$mean), ci_text(z$ci_low, z$ci_high), fmt(z$median), pformat(z$p_holm)), collapse = "; "), ".")
}, character(1))
sig <- tests %>% filter(p_holm < .05)
conclusion <- (
  if (!nrow(sig)) "None of the twelve primary tests rejected after Holm correction. This does not establish zero effects or equivalence."
  else paste0(nrow(sig), " of the twelve primary tests rejected after Holm correction: ",
    paste(paste(sig$version, unname(metric_labels[sig$metric])), collapse = ", "), ".")
)
heterogeneity <- paste(sprintf("%s/%s: %d improved, %d exactly unchanged, %d worsened",
  effects$version, unname(metric_labels[effects$metric]), effects$improved, effects$unchanged,
  effects$worsened), collapse = "; ")
icc_text <- (
  if (nrow(variance)) paste0("The complementary random-intercept models yielded ICCs of ",
    paste(paste(unname(metric_labels[variance$metric]), fmt(variance$ICC)), collapse = ", "),
    ". These estimates describe case-related variance after conditioning on version. Residual diagnostics are exported separately; the Gaussian model is secondary.")
  else "The optional random-intercept analysis was not run because lmerTest was unavailable. No variance-component claim is made."
)
magnitude_text <- paste(sprintf("%s/%s: mean absolute variant difference %s versus replication %s (paired excess %s, CI %s)",
  magnitude$version, unname(metric_labels[magnitude$metric]), fmt(magnitude$mean_abs_variant),
  fmt(magnitude$mean_abs_replication), fmt(magnitude$mean_abs_excess),
  ci_text(magnitude$ci_low, magnitude$ci_high)), collapse = "; ")
report <- c(
  "% Requires graphicx and booktabs. Paths are relative to analysis_sol_output.",
  "\\section{Results}", "\\subsection{Data completeness and exclusions}",
  sprintf("Of %d intended observations from %d benchmark cases, %d evaluations had all three scores and %d failed. The primary analysis retained %d complete cases (%d observations). Excluded cases: %s. Recorded reasons: %s. A parser error does not by itself identify whether the reference or generated diagram caused the failure.",
    nrow(raw), length(cases), sum(raw$valid), sum(!raw$valid), length(complete_ids),
    nrow(primary)/3, if (length(excluded_names)) paste(tex_escape(excluded_names), collapse = ", ") else "none", reason_text),
  "\\subsection{Baseline scores and repeated-generation variability}", baseline_text, ". ",
  fig("fig1_condition_means.pdf", "Condition means with pointwise 95\\% case-bootstrap intervals; complete cases only."),
  rep_text, ". Replication statistics use all available paired baseline scores. They quantify empirical repeated-generation variability, not a formal detection threshold.",
  "\\newpage", "\\subsection{Effects of textual conditions}",
  "V1 makes information implicit, V2 introduces ambiguity, V3 introduces a semantic anomaly, and V4 paraphrases the description. All differences are variant minus V0; negative values indicate lower reference similarity. Two-sided Wilcoxon signed-rank tests use tie and continuity corrections, with Holm adjustment over twelve tests. Signed-rank location inference assumes symmetric differences. Bootstrap intervals describe arithmetic mean differences and are pointwise, not multiplicity-adjusted.",
  condition_text, conclusion,
  fig("fig3_effects_and_replication.pdf", "Individual signed differences and mean estimates. The replication distribution is an empirical variability reference, not a statistical acceptance region."),
  "\\newpage", "\\subsection{Condition effects relative to generation variability}",
  magnitude_text, ". Comparisons of absolute differences use the same cases on both sides and paired bootstrap intervals for the mean excess. Shared baseline scores induce dependence, which the paired calculation preserves. These descriptive comparisons cannot establish a condition effect by themselves.",
  fig("fig6_absolute_differences.pdf", "Absolute condition-associated and replication differences; boxes show medians and interquartile ranges."),
  sprintf("A conservative normal-approximation sensitivity calculation used two-sided alpha 0.05/12, 80\\%% power, and the observed standard deviation of paired differences. Approximate minimum detectable mean effects ranged from %s to %s score units. These are conditional planning approximations, not exact Wilcoxon power calculations or evidence for the null hypothesis. Detailed per-contrast values and all-available-pair and sign-test sensitivity results are exported separately.",
    fmt(min(mde$mde_normal)), fmt(max(mde$mde_normal))),
  "\\newpage", "\\subsection{Case-level heterogeneity and limitations}",
  heterogeneity, ". Opposing case-level changes can cancel in the aggregate; an unchanged score does not establish an identical diagram.", icc_text,
  fig("fig2_paired_case_changes.pdf", "Within-case baseline-to-variant changes, separated by metric and condition.", "0.36\\textheight"),
  "Only one generation was obtained per manipulated condition and case. Individual changes cannot be separated cleanly into condition effects and stochastic generation variability. The second V0 run does not estimate condition-specific repeat variance. No independent manipulation check is present in the supplied files. Complete-case inference conditions on evaluability, and benchmark cases are not a random sample of all possible domain descriptions. Non-significance does not demonstrate equivalence or an ability to resolve every ambiguity. The metric measures reference similarity, not every aspect of semantic correctness."
)
writeLines(report, file.path(output_dir, "results_section.tex"))
writeLines(c("\\documentclass[10pt,a4paper]{article}",
  "\\usepackage[margin=18mm]{geometry}", "\\usepackage{graphicx,booktabs}",
  "\\begin{document}", "\\input{results_section.tex}", "\\end{document}"),
  file.path(output_dir, "results_standalone.tex"))
writeLines(c("Run source('analysis_sol.R') from the project root, with inputs in results/.",
  "Alternatively: Rscript analysis_sol.R INPUT_DIRECTORY OUTPUT_DIRECTORY",
  "Bootstrap: 10000 percentile resamples; seed 20260918. CIs are pointwise.",
  "Upload the entire output folder to Overleaf and compile results_standalone.tex.",
  "For thesis inclusion, adjust relative figure paths as needed; pagination depends on the thesis class.",
  "Inspect the PDFs and residual diagnostics before publication. No LaTeX compilation is performed by this script.",
  "Wilcoxon inference uses symmetry; sign tests are supplementary and target nonzero direction balance.",
  "All-available sensitivity adjusts its own family of 12 tests; it is not part of the primary family.",
  "Model identity and configuration come from supplied metadata, not an independent API verification."),
  file.path(output_dir, "README.txt"))
capture.output(sessionInfo(), file = file.path(output_dir, "session_info.txt"))
print(completeness)
print(tests %>% select(version, metric, n, mean, ci_low, ci_high, p_holm))
message("Analysis complete. Outputs: ", normalizePath(output_dir))

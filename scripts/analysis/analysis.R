# Statistical analysis of Metrik-4 experimental results
#
# Self-contained analysis: reads the raw `results` sheet, leaves the workbook
# unchanged, and writes derived tables and figures to results/analysis/.

# ============================================================
# 1. Packages and setup
# ============================================================

required_packages <- c("tidyverse", "readxl", "nlme")
missing_packages <- required_packages[
  !vapply(required_packages, requireNamespace, logical(1), quietly = TRUE)
]
if (length(missing_packages) > 0L) {
  stop(
    "Missing required R package(s): ", paste(missing_packages, collapse = ", "),
    ". Install them before running this script.", call. = FALSE
  )
}

suppressPackageStartupMessages({
  library(tidyverse)
  library(readxl)
  library(nlme)
})

options(
  contrasts = c("contr.treatment", "contr.poly"),
  dplyr.summarise.inform = FALSE,
  scipen = 999
)
set.seed(20260917)

ancestor_paths <- function(path) {
  if (is.na(path) || !nzchar(path)) return(character())
  path <- normalizePath(path, mustWork = FALSE)
  if (!dir.exists(path)) path <- dirname(path)
  ancestors <- character()
  repeat {
    ancestors <- c(ancestors, path)
    parent <- dirname(path)
    if (identical(parent, path)) break
    path <- parent
  }
  ancestors
}

get_source_path <- function() {
  arguments <- commandArgs(trailingOnly = FALSE)
  file_argument <- grep("^--file=", arguments, value = TRUE)
  if (length(file_argument) > 0L) {
    candidate <- sub("^--file=", "", file_argument[[1]])
    if (file.exists(candidate)) return(normalizePath(candidate, mustWork = TRUE))
  }

  source_files <- vapply(
    sys.frames(),
    function(frame) if (is.null(frame$ofile)) NA_character_ else as.character(frame$ofile),
    character(1)
  )
  source_files <- source_files[!is.na(source_files) & nzchar(source_files)]
  if (length(source_files) > 0L) {
    return(normalizePath(tail(source_files, 1L), mustWork = TRUE))
  }

  if (requireNamespace("rstudioapi", quietly = TRUE) && rstudioapi::isAvailable()) {
    active_path <- tryCatch(
      rstudioapi::getActiveDocumentContext()$path,
      error = function(e) ""
    )
    if (nzchar(active_path) && file.exists(active_path)) {
      return(normalizePath(active_path, mustWork = TRUE))
    }
  }
  NA_character_
}

find_project_root <- function() {
  configured_root <- Sys.getenv("DOMAIN_MODEL_EVAL_ROOT", unset = "")
  if (nzchar(configured_root)) {
    configured_root <- normalizePath(configured_root, mustWork = FALSE)
    if (!file.exists(file.path(configured_root, "results", "results.xlsx"))) {
      stop(
        "DOMAIN_MODEL_EVAL_ROOT does not contain results/results.xlsx: ",
        configured_root,
        call. = FALSE
      )
    }
    return(configured_root)
  }

  source_path <- get_source_path()
  candidates <- unique(c(
    ancestor_paths(source_path),
    ancestor_paths(getwd()),
    path.expand("~/PycharmProjects/domain_model_eval")
  ))
  valid_roots <- candidates[
    file.exists(file.path(candidates, "results", "results.xlsx"))
  ]
  if (length(valid_roots) > 0L) {
    return(normalizePath(valid_roots[[1]], mustWork = TRUE))
  }

  stop(
    "Could not locate the project root. Run the complete script from the project, ",
    "or set DOMAIN_MODEL_EVAL_ROOT to the directory containing results/results.xlsx.",
    call. = FALSE
  )
}

project_root <- find_project_root()
script_path <- file.path(project_root, "scripts", "analysis", "analysis.R")
input_workbook <- file.path(project_root, "results", "results.xlsx")
output_directory <- file.path(project_root, "results", "analysis")
dir.create(output_directory, recursive = TRUE, showWarnings = FALSE)
if (!file.exists(input_workbook)) stop("Input workbook not found: ", input_workbook, call. = FALSE)

version_levels <- paste0("V", 0:4)
comparison_levels <- paste0("V", 1:4)
score_columns <- c("class_score", "attribute_score", "association_score")
metric_labels <- c(
  class_score = "Classes",
  attribute_score = "Attributes",
  association_score = "Associations"
)

# The scores are stored as double-precision values. This tolerance only absorbs
# subtraction noise and is verified below against the smallest nonzero delta.
delta_tolerance <- 1e-12
bootstrap_repetitions <- 5000L

sample_skewness <- function(x) {
  x <- x[is.finite(x)]
  n <- length(x)
  if (n < 3L || isTRUE(all.equal(stats::sd(x), 0))) return(NA_real_)
  m3 <- mean((x - mean(x))^3)
  population_sd <- sqrt(mean((x - mean(x))^2))
  sqrt(n * (n - 1)) / (n - 2) * m3 / population_sd^3
}

mean_confidence_interval <- function(x, confidence_level = 0.95) {
  x <- x[is.finite(x)]
  n <- length(x)
  if (n < 2L) return(c(lower = NA_real_, upper = NA_real_))
  margin <- stats::qt((1 + confidence_level) / 2, df = n - 1) * stats::sd(x) / sqrt(n)
  c(lower = mean(x) - margin, upper = mean(x) + margin)
}

cohens_dz <- function(x) {
  x <- x[is.finite(x)]
  if (length(x) < 2L || stats::sd(x) == 0) return(NA_real_)
  mean(x) / stats::sd(x)
}

bootstrap_dz_interval <- function(x, repetitions = bootstrap_repetitions) {
  x <- x[is.finite(x)]
  if (length(x) < 2L || stats::sd(x) == 0) return(c(lower = NA_real_, upper = NA_real_))
  bootstrap_values <- replicate(repetitions, {
    resample <- sample(x, size = length(x), replace = TRUE)
    if (stats::sd(resample) == 0) NA_real_ else mean(resample) / stats::sd(resample)
  })
  setNames(
    stats::quantile(bootstrap_values, c(0.025, 0.975), na.rm = TRUE, names = FALSE, type = 6),
    c("lower", "upper")
  )
}

format_p_value <- function(x) {
  ifelse(is.na(x), "NA", ifelse(x < 0.001, "<0.001", sprintf("%.3f", x)))
}
format_number <- function(x, digits = 3L) {
  ifelse(is.na(x), "NA", formatC(x, format = "f", digits = digits))
}

# ============================================================
# 2. Import and validation
# ============================================================

# Keep the original imported object separate from every transformed object.
results_raw <- read_excel(input_workbook, sheet = "results")

required_columns <- c(
  "case_id", "version", "provider", "model_name", "run", "input_description",
  "reference_plantuml", "generated_plantuml", "prompt", "timestamp",
  "temperature", score_columns
)
missing_required_columns <- setdiff(required_columns, names(results_raw))
if (length(missing_required_columns) > 0L) {
  stop(
    "The workbook is missing required column(s): ",
    paste(missing_required_columns, collapse = ", "), call. = FALSE
  )
}

column_schema <- tibble(
  column = names(results_raw),
  r_type = map_chr(results_raw, ~ paste(class(.x), collapse = "/")),
  non_missing = map_int(results_raw, ~ sum(!is.na(.x))),
  missing = map_int(results_raw, ~ sum(is.na(.x)))
)
if (!all(vapply(results_raw[score_columns], is.numeric, logical(1)))) {
  stop("All score columns must be numeric.", call. = FALSE)
}

duplicate_keys <- results_raw |>
  count(case_id, version, name = "row_count") |>
  filter(row_count > 1L) |>
  arrange(case_id, version)
unexpected_versions <- results_raw |>
  filter(is.na(version) | !version %in% version_levels) |>
  distinct(case_id, version)
missing_identifiers <- results_raw |>
  filter(is.na(case_id) | case_id == "" | is.na(version) | version == "")
impossible_scores <- results_raw |>
  mutate(source_row = row_number() + 1L) |>
  pivot_longer(all_of(score_columns), names_to = "metric", values_to = "score") |>
  filter(!is.na(score) & (!is.finite(score) | score < 0 | score > 1)) |>
  select(source_row, case_id, version, metric, score)
design_grid <- expand_grid(
  case_id = sort(unique(results_raw$case_id)),
  version = version_levels
)
missing_design_cells <- design_grid |>
  anti_join(results_raw |> select(case_id, version), by = c("case_id", "version"))

write_csv(column_schema, file.path(output_directory, "column_schema.csv"))
write_csv(duplicate_keys, file.path(output_directory, "duplicate_case_version_keys.csv"))
write_csv(unexpected_versions, file.path(output_directory, "unexpected_versions.csv"))
write_csv(impossible_scores, file.path(output_directory, "impossible_scores.csv"))
write_csv(missing_design_cells, file.path(output_directory, "missing_design_cells.csv"))

if (nrow(duplicate_keys) > 0L) {
  stop("Duplicate case-version rows make pairing ambiguous; no rows were deleted.", call. = FALSE)
}
if (nrow(unexpected_versions) > 0L) {
  stop("Unexpected version values were found; see unexpected_versions.csv.", call. = FALSE)
}
if (nrow(missing_identifiers) > 0L) stop("Missing case or version identifiers were found.", call. = FALSE)
if (nrow(impossible_scores) > 0L) {
  stop("Scores outside [0, 1] were found; see impossible_scores.csv.", call. = FALSE)
}

results_prepared <- results_raw |>
  mutate(
    case_id = factor(case_id),
    version = factor(version, levels = version_levels),
    successful = if_all(
      all_of(score_columns),
      ~ !is.na(.x) & is.finite(.x) & .x >= 0 & .x <= 1
    ),
    all_scores_missing = if_all(all_of(score_columns), is.na),
    partial_score_missing = if_any(all_of(score_columns), is.na) & !all_scores_missing
  )

# ============================================================
# 3. Data preparation
# ============================================================

case_completeness <- results_prepared |>
  group_by(case_id) |>
  summarise(
    intended_versions = length(version_levels),
    observed_rows = n(),
    distinct_versions = n_distinct(version),
    successful_versions_n = sum(successful),
    successful_versions = paste(as.character(version[successful]), collapse = ", "),
    unsuccessful_versions = paste(as.character(version[!successful]), collapse = ", "),
    complete_case = observed_rows == length(version_levels) &
      distinct_versions == length(version_levels) & all(successful),
    .groups = "drop"
  ) |>
  arrange(case_id)

complete_case_ids <- case_completeness |> filter(complete_case) |> pull(case_id)
analysis_all_successful <- results_prepared |> filter(successful) |> droplevels()
analysis_complete <- results_prepared |>
  filter(case_id %in% complete_case_ids) |>
  droplevels()
if (nrow(analysis_complete) == 0L) {
  stop("No cases contain one successful observation for every version.", call. = FALSE)
}

to_metric_long <- function(data) {
  data |>
    select(case_id, version, all_of(score_columns)) |>
    pivot_longer(all_of(score_columns), names_to = "metric_key", values_to = "score") |>
    mutate(
      metric = factor(unname(metric_labels[metric_key]), levels = unname(metric_labels))
    )
}
complete_long <- to_metric_long(analysis_complete)
all_successful_long <- to_metric_long(analysis_all_successful)

data_dimensions <- tibble(
  dataset = c(
    "Raw intended observations", "All successful observations",
    "Primary complete-case observations"
  ),
  rows = c(nrow(results_raw), nrow(analysis_all_successful), nrow(analysis_complete)),
  cases = c(
    n_distinct(results_raw$case_id), n_distinct(analysis_all_successful$case_id),
    n_distinct(analysis_complete$case_id)
  ),
  versions = c(
    n_distinct(results_raw$version), n_distinct(analysis_all_successful$version),
    n_distinct(analysis_complete$version)
  )
)
write_csv(data_dimensions, file.path(output_directory, "data_dimensions.csv"))
write_csv(case_completeness, file.path(output_directory, "case_completeness.csv"))

# ============================================================
# 4. Missingness and failures
# ============================================================

failure_summary <- results_prepared |>
  group_by(version) |>
  summarise(
    intended_n = n(),
    successful_n = sum(successful),
    unsuccessful_n = sum(!successful),
    success_percent = 100 * successful_n / intended_n,
    failure_percent = 100 * unsuccessful_n / intended_n,
    all_scores_missing_n = sum(all_scores_missing),
    partial_score_missing_n = sum(partial_score_missing),
    .groups = "drop"
  )

incomplete_cases <- case_completeness |> filter(!complete_case)
unsuccessful_observations <- results_prepared |>
  filter(!successful) |>
  transmute(
    case_id = as.character(case_id),
    version = as.character(version),
    class_score,
    attribute_score,
    association_score,
    failure_definition = case_when(
      all_scores_missing ~ "All three metric scores missing",
      partial_score_missing ~ "One or more metric scores missing",
      TRUE ~ "Invalid score value"
    )
  )

validation_summary <- tibble(
  check = c(
    "Observed rows", "Distinct cases", "Intended case-version cells",
    "Missing case-version cells", "Duplicate case-version keys",
    "Successful observations", "Unsuccessful observations", "Complete cases",
    "Primary complete-case rows", "Impossible score values",
    "Partial score-missing rows"
  ),
  value = c(
    nrow(results_raw), n_distinct(results_raw$case_id),
    n_distinct(results_raw$case_id) * length(version_levels),
    nrow(missing_design_cells), nrow(duplicate_keys),
    sum(results_prepared$successful), sum(!results_prepared$successful),
    length(complete_case_ids), nrow(analysis_complete), nrow(impossible_scores),
    sum(results_prepared$partial_score_missing)
  )
)

write_csv(failure_summary, file.path(output_directory, "failure_summary.csv"))
write_csv(incomplete_cases, file.path(output_directory, "incomplete_cases.csv"))
write_csv(unsuccessful_observations, file.path(output_directory, "unsuccessful_observations.csv"))
write_csv(validation_summary, file.path(output_directory, "validation_summary.csv"))

# ============================================================
# 5. Descriptive statistics
# ============================================================

summarise_scores <- function(data, dataset_name) {
  data |>
    group_by(metric, version) |>
    summarise(
      n = n(),
      mean = mean(score),
      sd = sd(score),
      median = median(score),
      iqr = IQR(score),
      minimum = min(score),
      maximum = max(score),
      skewness = sample_skewness(score),
      exact_floor_percent = 100 * mean(score == 0),
      exact_ceiling_percent = 100 * mean(score == 1),
      near_floor_percent = 100 * mean(score <= 0.05),
      near_ceiling_percent = 100 * mean(score >= 0.95),
      tukey_extreme_n = {
        lower_fence <- quantile(score, 0.25) - 1.5 * IQR(score)
        upper_fence <- quantile(score, 0.75) + 1.5 * IQR(score)
        sum(score < lower_fence | score > upper_fence)
      },
      .groups = "drop"
    ) |>
    mutate(dataset = dataset_name, .before = 1L)
}

descriptive_statistics <- bind_rows(
  summarise_scores(complete_long, "Primary complete-case"),
  summarise_scores(all_successful_long, "All successful")
)
distribution_extremes <- complete_long |>
  group_by(metric, version) |>
  mutate(
    lower_fence = quantile(score, 0.25) - 1.5 * IQR(score),
    upper_fence = quantile(score, 0.75) + 1.5 * IQR(score)
  ) |>
  filter(score < lower_fence | score > upper_fence) |>
  ungroup() |>
  arrange(metric, version, score) |>
  mutate(case_id = as.character(case_id))

write_csv(descriptive_statistics, file.path(output_directory, "descriptive_statistics.csv"))
write_csv(distribution_extremes, file.path(output_directory, "distribution_extremes.csv"))

# ============================================================
# 6. V0-relative delta analysis
# ============================================================

delta_long <- complete_long |>
  group_by(case_id, metric) |>
  mutate(v0_score = score[version == "V0"], delta = score - v0_score) |>
  ungroup() |>
  filter(version != "V0") |>
  mutate(
    version = factor(as.character(version), levels = comparison_levels),
    change_direction = case_when(
      delta > delta_tolerance ~ "Improved",
      delta < -delta_tolerance ~ "Deteriorated",
      TRUE ~ "Unchanged"
    )
  )

nonzero_absolute_deltas <- abs(delta_long$delta[abs(delta_long$delta) > delta_tolerance])
smallest_nonzero_delta <- if (length(nonzero_absolute_deltas) == 0L) {
  NA_real_
} else {
  min(nonzero_absolute_deltas)
}
if (!is.na(smallest_nonzero_delta) && delta_tolerance >= smallest_nonzero_delta) {
  stop("The unchanged-score tolerance is too large for the observed precision.", call. = FALSE)
}

delta_effect_intervals <- delta_long |>
  group_by(metric, version) |>
  group_modify(~ {
    dz_interval <- bootstrap_dz_interval(.x$delta)
    tibble(
      cohens_dz = cohens_dz(.x$delta),
      cohens_dz_ci_low = dz_interval[["lower"]],
      cohens_dz_ci_high = dz_interval[["upper"]]
    )
  }) |>
  ungroup()

delta_summary <- delta_long |>
  group_by(metric, version) |>
  summarise(
    n = n(),
    mean_delta = mean(delta),
    median_delta = median(delta),
    sd_delta = sd(delta),
    mean_ci_low = mean_confidence_interval(delta)[["lower"]],
    mean_ci_high = mean_confidence_interval(delta)[["upper"]],
    improved_n = sum(change_direction == "Improved"),
    unchanged_n = sum(change_direction == "Unchanged"),
    deteriorated_n = sum(change_direction == "Deteriorated"),
    improved_percent = 100 * improved_n / n,
    unchanged_percent = 100 * unchanged_n / n,
    deteriorated_percent = 100 * deteriorated_n / n,
    .groups = "drop"
  ) |>
  left_join(delta_effect_intervals, by = c("metric", "version"))

delta_precision <- tibble(
  unchanged_tolerance = delta_tolerance,
  smallest_observed_nonzero_absolute_delta = smallest_nonzero_delta,
  exact_zero_delta_n = sum(delta_long$delta == 0),
  tolerance_classified_unchanged_n = sum(abs(delta_long$delta) <= delta_tolerance)
)

write_csv(
  delta_long |> mutate(case_id = as.character(case_id)),
  file.path(output_directory, "case_level_deltas.csv")
)
write_csv(delta_summary, file.path(output_directory, "delta_summary.csv"))
write_csv(delta_precision, file.path(output_directory, "delta_precision.csv"))

# ============================================================
# 7. Mixed-effects models
# ============================================================

fit_metric_models <- function(data, dataset_name) {
  models <- setNames(
    lapply(levels(data$metric), function(current_metric) {
      metric_data <- data |>
        filter(metric == current_metric) |>
        mutate(
          case_id = droplevels(case_id),
          version = factor(as.character(version), levels = version_levels)
        )
      nlme::lme(
        fixed = score ~ version,
        random = ~ 1 | case_id,
        data = metric_data,
        method = "REML",
        control = nlme::lmeControl(opt = "optim")
      )
    }),
    levels(data$metric)
  )

  diagnostics <- imap_dfr(models, function(model, current_metric) {
    model_residuals <- residuals(model)
    model_fitted <- fitted(model)
    variance_components <- nlme::VarCorr(model)
    shapiro_result <- shapiro.test(model_residuals)
    random_intercept_sd <- as.numeric(variance_components[1, "StdDev"])
    residual_scale <- as.numeric(variance_components[nrow(variance_components), "StdDev"])

    tibble(
      dataset = dataset_name,
      metric = current_metric,
      observations = nobs(model),
      cases = nlevels(droplevels(nlme::getGroups(model))),
      singular_fit = random_intercept_sd < 1e-5 * residual_scale,
      convergence_message = "None",
      residual_mean = mean(model_residuals),
      residual_sd = sd(model_residuals),
      residual_skewness = sample_skewness(model_residuals),
      shapiro_wilk_w = unname(shapiro_result$statistic),
      shapiro_wilk_p = shapiro_result$p.value,
      qq_correlation = cor(sort(model_residuals), qnorm(ppoints(length(model_residuals)))),
      residual_fitted_correlation = cor(model_residuals, model_fitted),
      absolute_residual_fitted_correlation = cor(abs(model_residuals), model_fitted),
      random_intercept_sd = random_intercept_sd,
      residual_scale = residual_scale
    )
  })
  list(models = models, diagnostics = diagnostics)
}

primary_model_bundle <- fit_metric_models(complete_long, "Primary complete-case")
all_successful_model_bundle <- fit_metric_models(all_successful_long, "All successful")
model_diagnostics <- bind_rows(
  primary_model_bundle$diagnostics,
  all_successful_model_bundle$diagnostics
)
write_csv(model_diagnostics, file.path(output_directory, "model_diagnostics.csv"))

# ============================================================
# 8. Planned contrasts and effect sizes
# ============================================================

# With V0 as the treatment-coded reference, the four fixed-effect coefficients
# are the planned V1-V4 versus V0 contrasts. `nlme` supplies denominator degrees
# of freedom and two-sided t tests for these reference contrasts.
extract_v0_contrasts <- function(model_bundle, dataset_name) {
  imap_dfr(model_bundle$models, function(model, current_metric) {
    coefficient_table <- summary(model)$tTable
    coefficient_names <- paste0("version", comparison_levels)
    if (!all(coefficient_names %in% rownames(coefficient_table))) {
      stop("A model is missing one or more V0-reference coefficients.", call. = FALSE)
    }

    estimates <- coefficient_table[coefficient_names, "Value"]
    standard_errors <- coefficient_table[coefficient_names, "Std.Error"]
    denominator_df <- coefficient_table[coefficient_names, "DF"]
    t_statistics <- coefficient_table[coefficient_names, "t-value"]
    tibble(
      dataset = dataset_name,
      metric = current_metric,
      version = factor(comparison_levels, levels = comparison_levels),
      comparison = paste(comparison_levels, "vs V0"),
      estimate = unname(estimates),
      std_error = unname(standard_errors),
      df = unname(denominator_df),
      conf_low = unname(estimates - qt(0.975, denominator_df) * standard_errors),
      conf_high = unname(estimates + qt(0.975, denominator_df) * standard_errors),
      t_statistic = unname(t_statistics),
      p_value = unname(coefficient_table[coefficient_names, "p-value"]),
      inference = "Two-sided t test with nlme denominator degrees of freedom"
    ) |>
      group_by(metric) |>
      mutate(p_holm = p.adjust(p_value, method = "holm")) |>
      ungroup()
  })
}

primary_contrasts <- extract_v0_contrasts(
  primary_model_bundle,
  "Primary complete-case"
) |>
  left_join(delta_effect_intervals, by = c("metric", "version"))

all_successful_contrasts <- extract_v0_contrasts(
  all_successful_model_bundle,
  "All successful"
)

robustness_comparison <- primary_contrasts |>
  select(
    metric, version, primary_estimate = estimate,
    primary_ci_low = conf_low, primary_ci_high = conf_high,
    primary_p_holm = p_holm
  ) |>
  left_join(
    all_successful_contrasts |>
      select(
        metric, version, all_successful_estimate = estimate,
        all_successful_ci_low = conf_low, all_successful_ci_high = conf_high,
        all_successful_p_holm = p_holm
      ),
    by = c("metric", "version")
  ) |>
  mutate(
    estimate_difference = all_successful_estimate - primary_estimate,
    sign_changed = sign(primary_estimate) != sign(all_successful_estimate),
    adjusted_significance_changed =
      (primary_p_holm < 0.05) != (all_successful_p_holm < 0.05)
  )

write_csv(primary_contrasts, file.path(output_directory, "mixed_model_planned_contrasts.csv"))
write_csv(all_successful_contrasts, file.path(output_directory, "mixed_model_all_successful.csv"))
write_csv(robustness_comparison, file.path(output_directory, "robustness_comparison.csv"))

# ============================================================
# 9. Sensitivity analyses, component comparison, heterogeneity
# ============================================================

friedman_results <- complete_long |>
  group_by(metric) |>
  group_modify(~ {
    test_result <- friedman.test(score ~ version | case_id, data = .x)
    tibble(
      statistic = unname(test_result$statistic),
      df = unname(test_result$parameter),
      p_value = test_result$p.value
    )
  }) |>
  ungroup() |>
  mutate(p_holm_across_metrics = p.adjust(p_value, method = "holm"))

safe_wilcoxon <- function(x) {
  test_result <- suppressWarnings(
    tryCatch(
      wilcox.test(
        x, mu = 0, alternative = "two.sided", exact = FALSE,
        correct = TRUE, conf.int = TRUE, conf.level = 0.95
      ),
      error = function(e) NULL
    )
  )
  if (is.null(test_result)) {
    return(tibble(
      statistic = NA_real_, hodges_lehmann = NA_real_,
      conf_low = NA_real_, conf_high = NA_real_, p_value = NA_real_
    ))
  }
  confidence_interval <- test_result$conf.int
  tibble(
    statistic = unname(test_result$statistic),
    hodges_lehmann = if (is.null(test_result$estimate)) NA_real_ else unname(test_result$estimate),
    conf_low = if (is.null(confidence_interval)) NA_real_ else confidence_interval[[1]],
    conf_high = if (is.null(confidence_interval)) NA_real_ else confidence_interval[[2]],
    p_value = test_result$p.value
  )
}

wilcoxon_results <- delta_long |>
  group_by(metric, version) |>
  group_modify(~ {
    bind_cols(
      tibble(
        paired_n = nrow(.x),
        nonzero_pair_n = sum(abs(.x$delta) > delta_tolerance),
        median_delta = median(.x$delta)
      ),
      safe_wilcoxon(.x$delta)
    )
  }) |>
  ungroup() |>
  group_by(metric) |>
  mutate(p_holm = p.adjust(p_value, method = "holm")) |>
  ungroup()

# Exploratory global test of whether the V0-relative effect differs by component.
delta_for_component_model <- delta_long |>
  mutate(
    case_id = droplevels(case_id),
    version = factor(as.character(version), levels = comparison_levels),
    metric = factor(as.character(metric), levels = unname(metric_labels))
  )
component_additive_model <- nlme::lme(
  fixed = delta ~ version + metric,
  random = ~ 1 | case_id,
  data = delta_for_component_model,
  method = "ML",
  control = nlme::lmeControl(opt = "optim")
)
component_interaction_model <- nlme::lme(
  fixed = delta ~ version * metric,
  random = ~ 1 | case_id,
  data = delta_for_component_model,
  method = "ML",
  control = nlme::lmeControl(opt = "optim")
)
component_interaction_anova <- anova(
  component_additive_model,
  component_interaction_model
)
lme_singular <- function(model, tolerance = 1e-5) {
  components <- nlme::VarCorr(model)
  random_sd <- as.numeric(components[1, "StdDev"])
  residual_sd <- as.numeric(components[nrow(components), "StdDev"])
  random_sd < tolerance * residual_sd
}
component_interaction_test <- tibble(
  comparison = "Version by metric interaction in V0-relative deltas",
  chi_square = component_interaction_anova$L.Ratio[[2]],
  df = component_interaction_anova$df[[2]] - component_interaction_anova$df[[1]],
  p_value = component_interaction_anova$`p-value`[[2]],
  additive_model_singular = lme_singular(component_additive_model),
  interaction_model_singular = lme_singular(component_interaction_model)
)

component_friedman_results <- delta_long |>
  group_by(version) |>
  group_modify(~ {
    test_result <- friedman.test(delta ~ metric | case_id, data = .x)
    tibble(
      statistic = unname(test_result$statistic),
      df = unname(test_result$parameter),
      p_value = test_result$p.value
    )
  }) |>
  ungroup() |>
  mutate(p_holm_across_versions = p.adjust(p_value, method = "holm"))

component_pairs <- tribble(
  ~metric_a, ~metric_b,
  "Classes", "Attributes",
  "Classes", "Associations",
  "Attributes", "Associations"
)
component_delta_wide <- delta_long |>
  select(case_id, version, metric, delta) |>
  pivot_wider(names_from = metric, values_from = delta)

component_pairwise_results <- map_dfr(comparison_levels, function(current_version) {
  version_data <- component_delta_wide |> filter(version == current_version)
  map2_dfr(component_pairs$metric_a, component_pairs$metric_b, function(metric_a, metric_b) {
    differences <- version_data[[metric_a]] - version_data[[metric_b]]
    t_result <- t.test(differences, mu = 0)
    wilcoxon_result <- safe_wilcoxon(differences)
    tibble(
      version = current_version,
      comparison = paste(metric_a, "minus", metric_b),
      mean_difference_in_delta = mean(differences),
      mean_ci_low = t_result$conf.int[[1]],
      mean_ci_high = t_result$conf.int[[2]],
      paired_t_p = t_result$p.value,
      wilcoxon_p = wilcoxon_result$p_value
    )
  })
}) |>
  group_by(version) |>
  mutate(
    paired_t_p_holm = p.adjust(paired_t_p, method = "holm"),
    wilcoxon_p_holm = p.adjust(wilcoxon_p, method = "holm")
  ) |>
  ungroup()

heterogeneity_summary <- delta_long |>
  group_by(metric, version) |>
  summarise(
    n = n(),
    mean_delta = mean(delta),
    sd_delta = sd(delta),
    iqr_delta = IQR(delta),
    minimum_delta = min(delta),
    maximum_delta = max(delta),
    maximum_absolute_delta = max(abs(delta)),
    top_three_absolute_share_percent = {
      absolute_deltas <- sort(abs(delta), decreasing = TRUE)
      denominator <- sum(absolute_deltas)
      if (denominator == 0) 0 else 100 * sum(head(absolute_deltas, 3L)) / denominator
    },
    .groups = "drop"
  )

largest_improvements <- delta_long |>
  group_by(metric, version) |>
  slice_max(delta, n = 3L, with_ties = FALSE) |>
  arrange(metric, version, desc(delta)) |>
  mutate(direction = "Largest improvement", rank = row_number()) |>
  ungroup()
largest_deteriorations <- delta_long |>
  group_by(metric, version) |>
  slice_min(delta, n = 3L, with_ties = FALSE) |>
  arrange(metric, version, delta) |>
  mutate(direction = "Largest deterioration", rank = row_number()) |>
  ungroup()
case_heterogeneity_extremes <- bind_rows(largest_improvements, largest_deteriorations) |>
  transmute(
    metric, version, direction, rank, case_id = as.character(case_id),
    v0_score, comparison_score = score, delta
  ) |>
  arrange(metric, version, direction, rank)

write_csv(friedman_results, file.path(output_directory, "friedman_tests.csv"))
write_csv(wilcoxon_results, file.path(output_directory, "wilcoxon_sensitivity.csv"))
write_csv(component_interaction_test, file.path(output_directory, "component_interaction_test.csv"))
write_csv(component_friedman_results, file.path(output_directory, "component_friedman_tests.csv"))
write_csv(component_pairwise_results, file.path(output_directory, "component_pairwise_deltas.csv"))
write_csv(heterogeneity_summary, file.path(output_directory, "heterogeneity_summary.csv"))
write_csv(case_heterogeneity_extremes, file.path(output_directory, "case_heterogeneity_extremes.csv"))

saveRDS(
  list(
    primary_metric_models = primary_model_bundle$models,
    all_successful_metric_models = all_successful_model_bundle$models,
    component_additive_model = component_additive_model,
    component_interaction_model = component_interaction_model
  ),
  file.path(output_directory, "fitted_models.rds")
)

# ============================================================
# 10. Visualizations and output
# ============================================================

version_palette <- c(
  V0 = "#4D4D4D", V1 = "#0072B2", V2 = "#009E73",
  V3 = "#D55E00", V4 = "#CC79A7"
)

theme_thesis <- function() {
  theme_minimal(base_family = "Helvetica", base_size = 10) +
    theme(
      panel.grid.minor = element_blank(),
      panel.grid.major.x = element_blank(),
      panel.grid.major.y = element_line(linewidth = 0.25, colour = "#D9D9D9"),
      strip.text = element_text(face = "bold", size = 10),
      axis.title = element_text(size = 10),
      axis.text = element_text(size = 9, colour = "#222222"),
      legend.position = "none",
      plot.title = element_text(face = "bold", size = 11, hjust = 0),
      plot.subtitle = element_text(size = 9, colour = "#444444"),
      plot.margin = margin(6, 8, 6, 6)
    )
}

score_axis_lower_limit <- floor(min(complete_long$score) * 10) / 10
score_distribution_figure <- ggplot(
  complete_long,
  aes(x = version, y = score, fill = version)
) +
  geom_violin(trim = TRUE, scale = "width", alpha = 0.24, colour = NA) +
  geom_boxplot(
    width = 0.20, outlier.shape = NA, alpha = 0.72,
    linewidth = 0.35, colour = "#202020"
  ) +
  geom_point(
    position = position_jitter(width = 0.065, height = 0, seed = 20260917),
    shape = 21, size = 0.9, stroke = 0.15, alpha = 0.45, colour = "white"
  ) +
  facet_wrap(~ metric, nrow = 1) +
  scale_fill_manual(values = version_palette) +
  scale_y_continuous(
    breaks = seq(score_axis_lower_limit, 1, by = 0.1),
    labels = scales::label_number(accuracy = 0.1)
  ) +
  coord_cartesian(ylim = c(score_axis_lower_limit, 1)) +
  labs(
    title = "Metrik-4 component scores by text condition",
    subtitle = paste0("Primary balanced sample: ", length(complete_case_ids), " benchmark cases"),
    x = "Text condition",
    y = "Similarity score"
  ) +
  theme_thesis()

contrast_plot_data <- primary_contrasts |>
  mutate(
    version = factor(as.character(version), levels = rev(comparison_levels)),
    metric = factor(as.character(metric), levels = unname(metric_labels))
  )
contrast_axis_limit <- max(
  abs(c(contrast_plot_data$conf_low, contrast_plot_data$conf_high)),
  na.rm = TRUE
) * 1.08

mixed_effect_figure <- ggplot(
  contrast_plot_data,
  aes(x = estimate, y = version, colour = version)
) +
  geom_vline(
    xintercept = 0, linetype = "dashed", linewidth = 0.45,
    colour = "#666666"
  ) +
  geom_segment(
    aes(x = conf_low, xend = conf_high, yend = version),
    linewidth = 0.8
  ) +
  geom_point(size = 2.2) +
  facet_wrap(~ metric, nrow = 1) +
  scale_colour_manual(values = version_palette[comparison_levels]) +
  scale_x_continuous(
    limits = c(-contrast_axis_limit, contrast_axis_limit),
    labels = scales::label_number(accuracy = 0.01)
  ) +
  labs(
    title = "Estimated differences from the original description",
    subtitle = "Linear mixed-effects models; points are estimates and bars are 95% confidence intervals",
    x = "Estimated score difference (Vx - V0)",
    y = NULL
  ) +
  theme_thesis()

ggsave(
  file.path(output_directory, "figure_1_score_distributions.pdf"),
  score_distribution_figure, device = cairo_pdf,
  width = 7.2, height = 3.45, units = "in"
)
ggsave(
  file.path(output_directory, "figure_1_score_distributions.png"),
  score_distribution_figure,
  width = 7.2, height = 3.45, units = "in", dpi = 300, bg = "white"
)
ggsave(
  file.path(output_directory, "figure_2_mixed_effects.pdf"),
  mixed_effect_figure, device = cairo_pdf,
  width = 7.2, height = 3.35, units = "in"
)
ggsave(
  file.path(output_directory, "figure_2_mixed_effects.png"),
  mixed_effect_figure,
  width = 7.2, height = 3.35, units = "in", dpi = 300, bg = "white"
)

thesis_results_table <- primary_contrasts |>
  transmute(
    Metric = as.character(metric),
    Comparison = comparison,
    Estimate = estimate,
    `CI low` = conf_low,
    `CI high` = conf_high,
    `Holm-adjusted p` = p_holm,
    `Cohen's dz` = cohens_dz,
    `dz CI low` = cohens_dz_ci_low,
    `dz CI high` = cohens_dz_ci_high
  )
write_csv(thesis_results_table, file.path(output_directory, "table_1_planned_contrasts.csv"))

# Generate a booktabs-compatible Overleaf table without manually entered results.
backslash <- intToUtf8(92)
row_ending <- paste0(backslash, backslash)
latex_rows <- thesis_results_table |>
  transmute(
    row = paste0(
      Metric, " & ", Comparison, " & ",
      format_number(Estimate), " [", format_number(`CI low`), ", ",
      format_number(`CI high`), "] & ",
      format_p_value(`Holm-adjusted p`), " & ",
      format_number(`Cohen's dz`), " [", format_number(`dz CI low`), ", ",
      format_number(`dz CI high`), "] ", row_ending
    )
  ) |>
  pull(row)

latex_table <- c(
  paste0(backslash, "begin{table}[t]"),
  paste0(backslash, "centering"),
  paste0(backslash, "caption{Planned V0-reference contrasts from the primary mixed-effects models.}"),
  paste0(backslash, "label{tab:planned-contrasts}"),
  paste0(backslash, "small"),
  paste0(backslash, "begin{tabular}{llccc}"),
  paste0(backslash, "toprule"),
  paste0(
    "Metric & Contrast & Estimate [95", backslash,
    "% CI] & Holm-adjusted $p$ & $d_z$ [95", backslash, "% CI] ", row_ending
  ),
  paste0(backslash, "midrule"),
  latex_rows,
  paste0(backslash, "bottomrule"),
  paste0(backslash, "end{tabular}"),
  paste0(backslash, "end{table}")
)
writeLines(latex_table, file.path(output_directory, "table_1_planned_contrasts.tex"))

capture.output(sessionInfo(), file = file.path(output_directory, "session_info.txt"))

cat("\nAnalysis completed successfully.\n")
cat("Input workbook: ", input_workbook, "\n", sep = "")
cat("Output directory: ", output_directory, "\n", sep = "")
cat("Raw rows: ", nrow(results_raw), "\n", sep = "")
cat("Successful rows: ", nrow(analysis_all_successful), "\n", sep = "")
cat("Complete cases: ", length(complete_case_ids), "\n", sep = "")
cat("Primary rows: ", nrow(analysis_complete), "\n", sep = "")
cat("V0 reference level: ", levels(analysis_complete$version)[[1]], "\n\n", sep = "")
print(
  primary_contrasts |>
    select(metric, comparison, estimate, conf_low, conf_high, p_holm, cohens_dz)
)

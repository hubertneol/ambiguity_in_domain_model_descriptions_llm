# Pattern Name
V1 – Implicit Information Transformation Pattern

## Problem and Intended Outcome
The purpose of this pattern is to transform a natural-language domain description so that selected model-relevant information is expressed implicitly rather than explicitly.

The transformed description should still allow the intended domain-model information to be inferred from context, while removing its direct linguistic expression.

## Motivation
This pattern is used to investigate how large language models react when information required for reconstructing a UML domain model is not stated explicitly.

The goal is to test whether implicit model-relevant information leads to changes in the generated domain model compared with the baseline description.

## Structure and Participants
Input:
- one original natural-language domain description

Transformation:
- select model-relevant information that is explicit in the baseline text,
- reformulate it so that the information is no longer directly stated,
- ensure that the information remains reasonably inferable from context.

Model-relevant information may concern:
- classes,
- attributes,
- relationships,
- cardinalities,
- constraints.

Constraints:
- preserve all unrelated model-relevant information,
- do not introduce ambiguity,
- do not introduce semantic anomalies,
- do not add new model-relevant information,
- change only what is necessary to make selected information implicit,
- keep the description grammatical and natural.

Output:
- one transformed domain description,
- no explanation or commentary.

## Realized Prototype
Input:

"A customer has a customer number and a name. Each customer places one or more orders."

Output:

"Customers are uniquely identifiable and may place one or more orders."

In the transformed version, the existence of identifying information remains inferable, but the attribute "customer number" is no longer explicitly stated.

## Consequences

### Strengths
- directly targets the distinction between explicit and implicit information,
- allows the influence of inferential requirements to be tested,
- keeps the overall domain context largely stable.

### Weaknesses
- the degree of implicitness may vary between cases,
- information considered inferable by one reader or model may not be inferable by another,
- manual validation may be necessary to ensure that the transformation does not also introduce ambiguity.
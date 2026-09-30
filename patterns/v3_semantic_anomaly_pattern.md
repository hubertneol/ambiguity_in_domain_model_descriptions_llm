# Pattern Name
V3 – Semantic Anomaly Transformation Pattern

## Problem and Intended Outcome
The purpose of this pattern is to introduce a deliberate semantic anomaly into an otherwise valid natural-language domain description.

The resulting statement should remain grammatically correct but contain meaning that is inconsistent, implausible, contradictory, or semantically incompatible with the described domain.

## Motivation
This pattern is used to investigate how large language models react to semantically anomalous information during domain-model generation.

The goal is to determine whether anomalous input is ignored, corrected, incorporated, or otherwise reflected in the generated UML model.

## Structure and Participants
Input:
- one original natural-language domain description

Transformation:
- select one model-relevant statement,
- modify it so that it becomes semantically anomalous within the domain.

The anomaly may concern:
- a class,
- an attribute,
- a relationship,
- a cardinality,
- a constraint.

Constraints:
- preserve grammatical correctness,
- do not intentionally introduce ambiguity,
- preserve unrelated information,
- do not introduce multiple independent anomalies unless required,
- do not add unrelated domain information,
- modify as little as necessary.

Output:
- one transformed domain description,
- no explanation of the anomaly.

## Realized Prototype
Input:

"Each employee works for one department."

Output:

"Each department works for one employee."

The sentence is grammatically valid, but the semantic roles have been altered in a way that is anomalous relative to the intended domain.

## Consequences

### Strengths
- provides a controlled way to test model robustness against semantically problematic input,
- can reveal whether the LLM corrects, ignores, or reproduces anomalous information,
- preserves grammatical surface structure.

### Weaknesses
- anomaly strength may differ across cases,
- some anomalies may also change factual domain content substantially,
- the distinction between anomaly and simple incorrect information must be defined clearly.
# Pattern Name
V2 – Non-Syntactic Ambiguity Transformation Pattern

## Problem and Intended Outcome
The purpose of this pattern is to transform a natural-language domain description so that it contains deliberate ambiguity affecting model-relevant information while remaining grammatically well formed.

The transformed description should permit more than one plausible semantic interpretation without relying on an ambiguous syntactic structure.

## Motivation
This pattern is used to investigate how large language models resolve ambiguity when constructing UML domain models from natural-language descriptions.

The goal is to determine whether non-syntactic ambiguity leads to structural differences in the generated model compared with the baseline.

## Structure and Participants
Input:
- one original natural-language domain description

Transformation:
- identify a model-relevant statement,
- rewrite it so that more than one plausible interpretation exists,
- keep the grammatical structure clear.

Possible targets include:
- unclear reference,
- ambiguous entity participation,
- ambiguous attribute ownership,
- ambiguous relationship interpretation,
- ambiguous cardinality or scope.

Constraints:
- do not intentionally create syntactic ambiguity,
- do not introduce a semantic contradiction,
- preserve unrelated model-relevant information,
- do not add unrelated domain information,
- modify as little as necessary,
- keep the text natural and grammatical.

Output:
- one transformed domain description,
- no explanation of the ambiguity.

## Realized Prototype
Input:

"A pilot flies an aircraft. The aircraft has a registration number."

Output:

"A pilot flies an aircraft. It has a registration number."

The pronoun "it" may create ambiguity about which entity owns the registration number while the sentence remains syntactically well formed.

## Consequences

### Strengths
- isolates ambiguity as an experimental factor,
- allows investigation of model interpretation under uncertain reference,
- can directly affect class, attribute, or relationship reconstruction.

### Weaknesses
- ambiguity may be interpreted differently by different readers,
- some transformations may accidentally become syntactic rather than non-syntactic,
- manual inspection is required to confirm that the intended ambiguity is actually present.
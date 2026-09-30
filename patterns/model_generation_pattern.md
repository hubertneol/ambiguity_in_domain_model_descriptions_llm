# Pattern Name
UML Domain Model Generation Pattern

## Problem and Intended Outcome
The purpose of this pattern is to transform a natural-language domain description into a UML class diagram expressed in PlantUML.

The generated diagram should represent the model-relevant information contained in the description, and should be produced in a form that can be processed automatically without manual correction.

## Motivation
This pattern produces the dependent variable of the experiment. While the four transformation patterns vary the input text, this pattern must remain constant so that the text condition is the only factor that differs between observations.

The generated diagram is compared with a reference domain model by an automated similarity metric. The output must therefore be syntactically acceptable to the metric's parser, and must contain the diagram alone, without surrounding explanation.

## Structure and Participants
Input:
- one natural-language domain description, in any of the five text conditions (V0–V4).

Transformation:
- identify the model-relevant information contained in the description,
- represent it as a UML class diagram,
- express the diagram as PlantUML.

Model-relevant information may concern:
- classes,
- attributes,
- attribute types,
- associations between classes,
- association multiplicities and cardinalities,
- generalizations and inheritance relationships.

Constraints:
- derive the model exclusively from the provided description,
- do not use external domain knowledge or assumptions beyond the description,
- restrict the output to a fixed subset of PlantUML notation,
- declare relationships outside class bodies,
- express inheritance as `Parent <|-- Child`, and do not use the keyword `extends`,
- do not use `actor`, `package`, `namespace`, `note`, `skinparam`, or stereotypes,
- return the diagram alone, without explanation, commentary, or Markdown code fences,
- assign no role or persona, so that persona effects do not vary between generations,
- apply the identical prompt to every case and every version,
- produce exactly one diagram per description.

Output:
- one PlantUML class diagram, delimited by `@startuml` and `@enduml`,
- no additional text.

## Realized Prototype
Input:

"A customer has a customer number and a name. Each customer places one or more orders."

Output:

```
@startuml
class Customer {
  customerNumber : String
  name : String
}

class Order {
}

Customer "1" -- "1..*" Order
@enduml
```

The description's entities become classes, its stated properties become typed attributes, and the stated relationship becomes an association carrying the multiplicity given in the text. No element is introduced that the description does not support.

## Consequences

### Strengths
- holding the prompt constant across all cases and versions isolates the text condition as the only varying factor,
- the explicit output template yields diagrams that can be parsed and scored without manual intervention,
- the output purity requirement removes the need to strip commentary before evaluation,
- the grounding constraint discourages the model from supplying domain knowledge that is absent from the description,
- the absence of a persona removes one source of uncontrolled variation.

### Weaknesses
- notation constraints may influence modelling decisions and not only notation, for example by encouraging particular relationship types,
- the notation constraints are not reliably observed; some generations continued to use unsupported syntax despite the explicit prohibition,
- restricting the notation excludes constructs that the evaluation parser cannot represent, so some legitimate modelling choices are unavailable to the model,
- a single generation per description provides no estimate of the variability of the output, so small differences between conditions cannot be separated from generation noise,
- the fixed prompt cannot compensate for descriptions in which the model-relevant information is genuinely underdetermined.

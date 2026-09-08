# Text-to-SQL Evaluation Framework

## Objective

Measure whether an AI system produces correct, safe, and semantically valid SQL 
for enterprise analytics questions.

## Evaluation Dimensions

A SQL query that executes successfully is not necessarily correct.

For example, consider the question:

> What was revenue by region last quarter?

The generated SQL must be evaluated across multiple dimensions:

1. **Execution correctness** — Does the SQL execute successfully?
2. **Schema correctness** — Are all referenced tables and columns valid?
3. **Join correctness** — Does the query use approved relationships between entities?
4. **Metric correctness** — Does it use the approved business definition of revenue?
5. **Grain correctness** — Is the data aggregated at the appropriate level?
6. **Filter correctness** — Are temporal and business filters interpreted correctly?
7. **Security correctness** — Does the query comply with access controls and PII policies?
8. **Result correctness** — Does the query ultimately produce the expected business answer?

SQL execution success does not imply semantic correctness, and semantic correctness does not automatically imply business-answer correctness.

## Expected System Behavior

A trustworthy system is not required to answer every question.

Each evaluation case defines one expected behavior:

- **answer** — sufficient governed context exists to produce an answer.
- **clarify** — the request contains ambiguity that must be resolved before answering.
- **refuse** — answering would be unsupported or unauthorized.

A correct clarification or refusal is a successful evaluation outcome. Conversely,
an answer can fail even when its SQL executes successfully.

## Root-Cause Classification

Evaluation cases classify the enterprise-data risks they are designed to expose.
A case may contain more than one root cause.

The initial controlled-failure taxonomy is:

- **metric** — a business measure lacks an authoritative definition.
- **grain** — a measure is evaluated or aggregated at an inappropriate level.
- **dimension** — a business dimension is ambiguous or insufficiently defined.
- **temporal** — the available data cannot establish what was true at the required time.
- **security** — the requested access or result violates authorization or data policy.
- **identity** — the available data cannot establish canonical entity identity.

Root-cause classification is separate from SQL correctness. A query may be
syntactically valid, reference valid schema, and execute successfully while still
producing an unsafe or semantically invalid business result.

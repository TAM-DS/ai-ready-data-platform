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

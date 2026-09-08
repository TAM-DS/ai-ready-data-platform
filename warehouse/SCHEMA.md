

# Retail Analytics Warehouse

## Purpose

This warehouse models a fictional enterprise retailer undergoing a legacy-to-modern data platform migration.

The schema intentionally contains realistic ambiguity that can cause a text-to-SQL system to generate syntactically valid but semantically incorrect queries.

The baseline experiment measures whether an ungrounded system can correctly reason about these ambiguities before a semantic layer is introduced.

## Failure Domains

The warehouse is designed to expose five classes of semantic risk:

1. **Metric ambiguity** — multiple plausible definitions of the same business concept.
2. **Join ambiguity** — multiple technically possible relationships between entities.
3. **Grain ambiguity** — tables representing different levels of business detail.
4. **Security ambiguity** — accessible data does not necessarily imply authorized data.
5. **Dimension ambiguity** — the same business term may refer to different organizational classifications, hierarchies, or legacy definitions.


## Core Tables

### `sales_orders`

**Purpose:** Represents completed retail orders in the modern transactional system.

**Grain:** One row per order.

| Column | Description |
|---|---|
| `order_id` | Unique identifier for the order |
| `customer_id` | Customer who placed the order |
| `store_id` | Store associated with the order |
| `order_date` | Date the order was placed |
| `gross_amount` | Order value before discounts and returns |
| `discount_amount` | Discounts applied to the order |
| `returned_amount` | Value subsequently returned |

**Relationship:** Many `sales_orders` rows may reference one `stores` row through `store_id`. One `sales_orders` row may be referenced by many `order_items` rows through `order_id`.

**Semantic risk:** Monetary columns exist at the order grain. Joining this table to a lower-grain table such as `order_items` can duplicate order-level monetary values if aggregation occurs after the join.

**Metric risk:** Revenue is not a property of the raw data; it is a business policy defined over the data. `gross_amount`, `discount_amount`, and `returned_amount` support multiple plausible and internally consistent revenue calculations, but the schema provides no signal identifying which definition is authoritative. Without an explicit governed metric definition, an AI system or human analyst may select a valid calculation that is nevertheless inconsistent with enterprise reporting policy.


### `order_items`

**Purpose:** Represents individual product line items within each retail order.

**Grain:** One row per order line item.

| Column | Description |
|---|---|
| `order_item_id` | Unique identifier for the line item |
| `order_id` | Order containing the line item |
| `product_id` | Product sold |
| `quantity` | Number of units sold |
| `unit_price` | Selling price per unit |
| `unit_cost` | Cost per unit |

**Relationship:** Many `order_items` rows may belong to one `sales_orders` row through `order_id`.

**Semantic risk:** Joining `sales_orders` to `order_items` changes the effective grain from one row per order to one row per order line item. Order-level monetary measures can be duplicated if they are aggregated after this join.


### `products`

**Purpose:** Represents the retailer's product catalog.

**Grain:** One row per unique product.

| Column | Description |
|---|---|
| `product_id` | Unique identifier for the product |
| `product_name` | Product name |
| `category` | Product category |
| `brand` | Product brand |

**Relationship:** One `products` row may be referenced by many `order_items` rows through `product_id`.



### `business_regions`

**Purpose:** Represents the retailer's organizational hierarchy used to group stores for business reporting and analysis.

**Grain:** One row per unique business-region hierarchy node.

| Column | Description |
|---|---|
| `business_region_id` | Unique identifier for the business-region hierarchy node |
| `region_name` | Business name of the region, such as `Northeast`, `West Coast`, or `EMEA South` |
| `region_code` | Short business code used to identify the region |
| `parent_region_id` | Identifier of the parent node in the business-region hierarchy; null for the top-level node |
| `region_level` | Numeric depth of the node within the hierarchy |
| `region_type` | Business meaning of the node, such as `continent`, `country`, `business_region`, `market`, or `district` |
| `is_active` | Indicates whether the hierarchy node is currently active |

**Relationship:** One `business_regions` row may be the parent of many other `business_regions` rows through `parent_region_id`. A business-region hierarchy node may also be associated with many `stores` rows through `business_region_id`.

**Semantic risk:** Geographic location and organizational region are not interchangeable. The same term, such as `region`, may refer to different levels of the business hierarchy or to legacy organizational definitions. Queries that do not resolve the intended business meaning can execute successfully while returning results grouped by the wrong organizational structure.


### `states`

**Purpose:** Canonical reference table for state/province-level geographic entities. Every table referencing a state must resolve to a single, consistent identity rather than maintaining independent free-text representations.

**Grain:** One row per state/province per country. `state_code` is defined within a country namespace and must not be treated as globally unique. The natural key is the composite (`country_code`, `state_code`), while `state_id` is the surrogate key referenced by downstream foreign keys.

| Column | Description |
|---|---|
| `state_id` | Surrogate primary key referenced by downstream foreign keys |
| `state_code` | Approved abbreviated state/province code, such as `TX` |
| `state_name` | Full display name, such as `Texas` |
| `country_code` | Country containing the state/province; part of the natural key |

**Relationship:** One `states` row may be referenced by many `stores` and `customers` rows through `state_id`. Future entities requiring state/province geography should reference the same canonical identity.

**Semantic risk:** Low by design. This table answers which canonical geographic entity a reference represents; it does not define sales regions, markets, territories, or other organizational classifications. Adding those concepts here would introduce unnecessary semantic ambiguity.

**Identity risk:** This table mitigates inconsistent representations of the same geographic entity across source systems, such as `TX`, `Tex.`, `Texas`, or `texas`. Such fragmentation can distort joins and aggregations and reduce trust in analytical results. Downstream entities therefore reference `state_id` rather than independently interpreting `state_code` or `state_name`. The foreign key enforces a canonical reference and referential integrity; it does not guarantee that the source selected the correct real-world state.


### `stores`

**Purpose:** Master data for physical retail locations. Provides the authoritative source of store attributes and the primary path from transactional data into geographic and organizational reporting hierarchies.

**Grain:** One row per unique retail store.

| Column | Description |
|---|---|
| `store_id` | Unique identifier for the store |
| `store_name` | Official or display name of the store |
| `city` | City in which the store is physically located |
| `state_id` | Foreign key identifying the store's state or province |
| `business_region_id` | Foreign key identifying the store's current organizational reporting region |

**Relationship:** One `stores` row may be referenced by many `sales_orders` rows through `store_id`. Each store is associated with one current business-region hierarchy node through `business_region_id`.

**Semantic risk:** Geographic location and organizational assignment are not interchangeable. A store may remain physically located in the same state while its `business_region_id` changes as the company reorganizes territories. Treating the current organizational assignment as permanent can silently misattribute historical orders to the wrong business region. Missing or null `business_region_id` values may also create unassigned reporting groups that agents must not silently reinterpret.



### `customers`

**Purpose:** Master data for individual and business customers. Provides the authoritative customer identity used to associate transactional activity with customer classifications and attributes.

**Grain:** One row per unique customer.

| Column | Description |
|---|---|
| `customer_id` | Unique identifier for the customer |
| `customer_type` | Customer classification, such as `INDIVIDUAL` or `BUSINESS` |
| `customer_name` | Name of the individual or business account |
| `email` | Customer email address |
| `city` | Customer's current city |
| `state_id` | Foreign key identifying the customer's current state or province |
| `loyalty_tier` | Current loyalty classification, such as `STANDARD`, `GOLD`, or `VIP` |
| `created_date` | Date the customer record was created |


**Relationship:** One `customers` row may be referenced by many `sales_orders` rows through `customer_id`.

**Semantic risk:** Customer attributes such as location and loyalty status may change over time, so current values must not automatically be interpreted as historically accurate for earlier transactions. Cu>




"""Create the DuckDB tables documented in warehouse/SCHEMA.md."""

from pathlib import Path

import duckdb


def build(database: str | Path = Path(__file__).with_name("warehouse.duckdb")) -> None:
    """Create missing tables without replacing existing tables or data."""
    with duckdb.connect(str(database)) as connection:
        connection.execute("BEGIN TRANSACTION")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS business_regions (
                business_region_id BIGINT PRIMARY KEY,
                region_name VARCHAR,
                region_code VARCHAR,
                parent_region_id BIGINT REFERENCES business_regions(business_region_id),
                region_level INTEGER,
                region_type VARCHAR,
                is_active BOOLEAN
            );

            CREATE TABLE IF NOT EXISTS states (
                state_id BIGINT PRIMARY KEY,
                state_code VARCHAR NOT NULL,
                state_name VARCHAR,
                country_code VARCHAR NOT NULL,
                UNIQUE (country_code, state_code)
            );

            CREATE TABLE IF NOT EXISTS products (
                product_id BIGINT PRIMARY KEY,
                product_name VARCHAR,
                category VARCHAR,
                brand VARCHAR
            );

            CREATE TABLE IF NOT EXISTS stores (
                store_id BIGINT PRIMARY KEY,
                store_name VARCHAR,
                city VARCHAR,
                state_id BIGINT REFERENCES states(state_id),
                business_region_id BIGINT REFERENCES business_regions(business_region_id)
            );

            CREATE TABLE IF NOT EXISTS customers (
                customer_id BIGINT PRIMARY KEY,
                customer_type VARCHAR,
                customer_name VARCHAR,
                email VARCHAR,
                city VARCHAR,
                state_id BIGINT REFERENCES states(state_id),
                loyalty_tier VARCHAR,
                created_date DATE
            );

            CREATE TABLE IF NOT EXISTS sales_orders (
                order_id BIGINT PRIMARY KEY,
                customer_id BIGINT REFERENCES customers(customer_id),
                store_id BIGINT REFERENCES stores(store_id),
                order_date DATE,
                gross_amount DECIMAL(18, 2),
                discount_amount DECIMAL(18, 2),
                returned_amount DECIMAL(18, 2)
            );

            CREATE TABLE IF NOT EXISTS order_items (
                order_item_id BIGINT PRIMARY KEY,
                order_id BIGINT REFERENCES sales_orders(order_id),
                product_id BIGINT REFERENCES products(product_id),
                quantity INTEGER,
                unit_price DECIMAL(18, 2),
                unit_cost DECIMAL(18, 2)
            );
            """
        )
        connection.execute("COMMIT")


if __name__ == "__main__":
    build()

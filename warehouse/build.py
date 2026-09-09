"""Create the documented DuckDB tables and insert the baseline seed data."""

from pathlib import Path

import duckdb


def build(database: str | Path = Path(__file__).with_name("warehouse.duckdb")) -> None:
    """Create missing tables and seed rows without replacing existing data."""
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
        connection.execute(
            """
            INSERT INTO states (state_id, state_code, state_name, country_code)
            VALUES
                (1, 'TX', 'Texas', 'US'),
                (2, 'MA', 'Massachusetts', 'US')
            ON CONFLICT (state_id) DO NOTHING;

            INSERT INTO business_regions (
                business_region_id, region_name, region_code, parent_region_id,
                region_level, region_type, is_active
            ) VALUES (1, 'United States', 'US', NULL, 1, 'country', TRUE)
            ON CONFLICT (business_region_id) DO NOTHING;

            INSERT INTO business_regions (
                business_region_id, region_name, region_code, parent_region_id,
                region_level, region_type, is_active
            ) VALUES (2, 'South Central', 'SOUTH_CENT', 1, 2, 'business_region', TRUE)
            ON CONFLICT (business_region_id) DO NOTHING;

            INSERT INTO stores (
                store_id, store_name, city, state_id, business_region_id
            ) VALUES (101, 'Headquarters_HQ', 'Austin', 1, 2)
            ON CONFLICT (store_id) DO NOTHING;

            INSERT INTO customers (
                customer_id, customer_type, customer_name, email, city,
                state_id, loyalty_tier, created_date
            ) VALUES
                (1001, 'individual', 'Jane Doe', 'jane.doe@gmail.com',
                 'Austin', 1, 'VIP', DATE '2022-09-08'),
                (1002, 'individual', 'Thomas Wilkerson', 'tw@gmail.com',
                 'Austin', 1, 'VIP', DATE '2024-01-15')
            ON CONFLICT (customer_id) DO NOTHING;

            INSERT INTO products (product_id, product_name, category, brand)
            VALUES
                (1, 'D3_Gummies', 'Health', 'Force Factor'),
                (2, 'Pure Catnip', 'Pets', 'Cates Meow'),
                (3, 'Mackerel', 'Grocery', 'Wild Planet')
            ON CONFLICT (product_id) DO NOTHING;

            INSERT INTO sales_orders (
                order_id, customer_id, store_id, order_date,
                gross_amount, discount_amount, returned_amount
            ) VALUES
                (5001, 1001, 101, DATE '2025-09-08', 100.00, 10.00, 20.00),
                (5002, 1001, 101, DATE '2026-09-01', 100.00, 0.00, 0.00),
                (5003, 1001, 101, DATE '2023-06-10', 2000.00, 0.00, 0.00),
                (5004, 1002, 101, DATE '2026-08-15', 900.00, 0.00, 0.00)
            ON CONFLICT (order_id) DO NOTHING;

            INSERT INTO order_items (
                order_item_id, order_id, product_id, quantity, unit_price, unit_cost
            ) VALUES
                (500201, 5002, 1, 1, 20.00, 12.00),
                (500202, 5002, 2, 1, 50.00, 25.00),
                (500203, 5002, 3, 1, 30.00, 18.00),
                (500401, 5004, 3, 3, 300.00, 192.00)
            ON CONFLICT (order_item_id) DO NOTHING;
            """
        )
        connection.execute("COMMIT")


if __name__ == "__main__":
    build()

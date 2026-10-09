view: orders {
  derived_table: {
    sql: SELECT id FROM raw.orders ;;
  }
  dimension: id { sql: ${TABLE}.id ;; }
}

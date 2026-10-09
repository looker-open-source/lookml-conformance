view: orders {
  derived_table: {
    sql: SELECT id FROM `@{RAW_DATASET}.orders` ;;
  }
  dimension: id { sql: ${TABLE}.id ;; }
}
